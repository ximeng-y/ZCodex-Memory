"""Stop Hook 使用的后台记忆提取。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterable

from .config import Config
from .errors import ExtractionError, ValidationError
from .frontmatter import validate_name, validate_type
from .session_state import complete_snapshot, delete_turn, list_pending, read_snapshot
from .store import ProjectMemoryStore
from .util import append_log, utc_now_iso


PLUGIN_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA_PATH = PLUGIN_ROOT / "schemas" / "extraction.schema.json"


def build_extraction_prompt(snapshot: dict[str, Any], *, manifest_text: str) -> str:
    raw_prompt = str(snapshot.get("prompt", ""))
    raw_assistant = str(snapshot.get("assistant_message", ""))
    prompt = raw_prompt[:12000]
    assistant = raw_assistant[:20000]
    if len(raw_prompt) > 12000:
        prompt += "\n[用户消息已截断]"
    if len(raw_assistant) > 20000:
        assistant += "\n[助手消息已截断]"

    return f'''你是 ZCodex Memory 的后台提取器。只分析下面这一轮对话，不要读取源码、Git 或网络，也不要调用任何写入工具。

你的任务是返回 JSON 操作列表，由外部程序校验并写入文件。如果没有值得长期保存的内容，返回 {{"operations":[]}}。

只允许保存：
- user：用户身份、稳定偏好、专业背景
- feedback：用户对工作方式的纠正或确认
- project：无法从代码或 Git 推导的项目目标、约束、长期方向
- reference：外部资源、链接、面板、票据

不要保存：代码结构、Git 历史、AGENTS.md 已有内容、只对当前对话有效的信息、临时任务状态。
已有记忆优先 update，不要创建语义重复文件。feedback/project 类型正文优先包含 `**Why:**` 和 `**How to apply:**`。

## 已有记忆 Manifest

{manifest_text or "（空）"}

## 本轮用户消息

{prompt or "（空）"}

## 本轮助手最终消息

{assistant or "（空）"}

## 输出要求

只输出符合 output schema 的 JSON。create 必须提供 name、description、type、body；update/delete 必须提供 filename 或 name；单次最多 10 个操作。'''


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError("提取操作字段必须是字符串")
    value = value.strip()
    return value or None


def validate_operations(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValidationError("提取结果必须是 JSON 对象")
    operations = payload.get("operations")
    if not isinstance(operations, list):
        raise ValidationError("提取结果必须包含 operations 数组")
    if len(operations) > 10:
        raise ValidationError("单次最多应用 10 个提取操作")

    validated: list[dict[str, Any]] = []
    for index, raw in enumerate(operations):
        if not isinstance(raw, dict):
            raise ValidationError(f"第 {index + 1} 个操作必须是对象")
        action = _as_optional_str(raw.get("action"))
        if action not in {"create", "update", "delete"}:
            raise ValidationError(f"第 {index + 1} 个操作 action 无效")
        item = {
            "action": action,
            "filename": _as_optional_str(raw.get("filename")),
            "name": _as_optional_str(raw.get("name")),
            "description": _as_optional_str(raw.get("description")),
            "type": _as_optional_str(raw.get("type")),
            "title": _as_optional_str(raw.get("title")),
            "body": _as_optional_str(raw.get("body")),
            "reason": _as_optional_str(raw.get("reason")) or "",
        }
        if item["name"]:
            item["name"] = validate_name(item["name"])
        if item["type"]:
            item["type"] = validate_type(item["type"])
        if action == "create":
            for required in ("name", "description", "type", "body"):
                if not item[required]:
                    raise ValidationError(f"create 缺少字段: {required}")
        else:
            if not item["filename"] and not item["name"]:
                raise ValidationError(f"{action} 必须提供 filename 或 name")
        validated.append(item)
    return validated


def apply_operations(store: ProjectMemoryStore, operations: Iterable[dict[str, Any]], *, session_id: str | None = None) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for operation in operations:
        action = operation["action"]
        if action in {"create", "update"}:
            result = store.write(
                action="upsert" if action == "create" else "update",
                filename=operation.get("filename"),
                name=operation.get("name"),
                description=operation.get("description"),
                memory_type=operation.get("type"),
                body=operation.get("body"),
                title=operation.get("title"),
                origin_session_id=session_id,
            )
        else:
            result = store.forget(filename=operation.get("filename"), name=operation.get("name"), reason=operation.get("reason"))
        results.append({"action": action, "result": result})
    return results


def resolve_codex_executable() -> str:
    explicit = os.environ.get("CODEX_CLI_PATH")
    if explicit and Path(explicit).exists():
        return explicit
    found = shutil.which("codex")
    if found:
        return found
    raise ExtractionError("找不到 codex 可执行文件（CODEX_CLI_PATH 或 PATH）")


def _subprocess_command(codex_path: str, args: list[str]) -> list[str]:
    path = Path(codex_path)
    if path.suffix.lower() in {".cmd", ".bat"}:
        command_line = subprocess.list2cmdline([str(path), *args])
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", command_line]
    if path.suffix.lower() == ".ps1":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(path), *args]
    return [str(path), *args]


def run_extraction(
    store: ProjectMemoryStore,
    snapshot: dict[str, Any],
    *,
    config: Config,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
    timeout: int = 170,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    codex = resolve_codex_executable()
    manifest = store.manifest(limit=200)
    manifest_text = "\n".join(
        f"- [{item.memory_type or 'unknown'}] {item.filename}: {item.description or ''}".rstrip()
        for item in manifest
    )
    prompt = build_extraction_prompt(snapshot, manifest_text=manifest_text)

    with tempfile.TemporaryDirectory(prefix="zcodex-memory-extract-") as temp_dir:
        output_path = Path(temp_dir) / "result.json"
        args = [
            "-a",
            "never",
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--disable",
            "hooks",
            "-s",
            "read-only",
            "--output-schema",
            str(schema_path),
            "-o",
            str(output_path),
            "-C",
            str(snapshot.get("cwd") or store.workspace_path),
        ]
        model = config.extract_model or _as_optional_str(snapshot.get("model"))
        if model:
            args.extend(["-m", model])
        env = os.environ.copy()
        env["CODEX_ZCODEX_MEMORY_EXTRACTOR"] = "1"
        completed = runner(
            _subprocess_command(codex, args),
            input=prompt,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            env=env,
        )
        if completed.returncode != 0:
            raise ExtractionError(f"codex exec 失败，退出码 {completed.returncode}: {completed.stderr[-1000:]}")
        if not output_path.exists():
            raise ExtractionError("codex exec 未生成最终结果文件")
        try:
            payload = json.loads(output_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise ExtractionError(f"提取结果不是合法 JSON: {exc}") from exc

    operations = validate_operations(payload)
    if not operations:
        return {"status": "no-op", "operations": []}
    results = apply_operations(store, operations, session_id=str(snapshot.get("session_id") or "") or None)
    return {"status": "success", "operations": results}


def drain_queue(
    *,
    config: Config,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
    timeout: int = 170,
    limit: int = 3,
) -> dict[str, Any]:
    processed = 0
    succeeded = 0
    failed = 0
    queue_dirs = config.state_root / "queue"
    directories = sorted(queue_dirs.glob("*")) if queue_dirs.exists() else []
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in list_pending(config, project_state_id=directory.name)[:limit]:
            claimed = path.with_suffix(".processing")
            try:
                path.replace(claimed)
            except OSError:
                continue
            processed += 1
            try:
                snapshot = read_snapshot(claimed)
                workspace = str(snapshot.get("cwd") or "")
                if not workspace:
                    raise ExtractionError("提取快照缺少 cwd")
                store = ProjectMemoryStore(config, workspace, snapshot.get("workspace_identity") if isinstance(snapshot.get("workspace_identity"), str) else None)
                result = run_extraction(store, snapshot, config=config, schema_path=schema_path, timeout=timeout)
                complete_snapshot(claimed)
                delete_turn(config, session_id=str(snapshot.get("session_id") or ""), turn_id=str(snapshot.get("turn_id") or ""))
                succeeded += 1
                append_log(config.state_root / "logs" / "extract.log", f"success {snapshot.get('session_id')}/{snapshot.get('turn_id')}: {result['status']}")
            except Exception as exc:
                failed += 1
                try:
                    claimed.replace(path)
                except OSError:
                    pass
                append_log(config.state_root / "logs" / "extract.log", f"error {claimed.name}: {type(exc).__name__}: {exc}")
                break
    return {"processed": processed, "succeeded": succeeded, "failed": failed, "finished_at": utc_now_iso()}
