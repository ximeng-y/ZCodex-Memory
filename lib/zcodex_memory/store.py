"""ZCode 文件记忆存储后端。"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from .config import Config
from .errors import BackendError, ConflictError, LockError, ValidationError
from .frontmatter import MemoryDocument, parse_memory_document, render_memory_document, validate_name, validate_type
from .indexing import (
    format_index_for_context,
    pointer_line,
    remove_index_text,
    target_filenames,
    update_index_text,
    validate_filename,
)
from .paths import resolve_project_memory_root, state_project_key
from .util import FileFingerprint, append_log, atomic_write_text, read_json, utc_now_iso, write_json


INDEX_NAME = "MEMORY.md"
TRASH_DIR = ".trash"
STATE_DIR = ".state"


@dataclass(frozen=True)
class MemoryItem:
    filename: str
    name: str | None
    description: str | None
    memory_type: str | None
    mtime: float
    path: Path


@dataclass(frozen=True)
class SearchResult:
    filename: str
    name: str | None
    description: str | None
    memory_type: str | None
    score: int
    snippet: str


class ZCodeFilesBackend:
    name = "zcode-files"

    def __init__(self, config: Config) -> None:
        self.config = config

    def resolve_root(self, workspace_path: str | os.PathLike[str], workspace_identity: str | None) -> Path:
        return resolve_project_memory_root(
            self.config.cli_storage_root,
            workspace_path,
            workspace_identity,
        )


def create_backend(config: Config):
    if config.backend == "zcode-files":
        return ZCodeFilesBackend(config)
    raise BackendError(f"不支持的 backend: {config.backend}")


class ProjectMemoryStore:
    """项目级 Memory 文件库。"""

    def __init__(
        self,
        config: Config,
        workspace_path: str | os.PathLike[str],
        workspace_identity: str | None = None,
        *,
        backend=None,
    ) -> None:
        self.config = config
        self.workspace_path = os.path.abspath(os.path.normpath(os.fspath(workspace_path)))
        self.workspace_identity = workspace_identity.strip() if workspace_identity else None
        self.backend = backend or create_backend(config)
        self.root = self.backend.resolve_root(self.workspace_path, self.workspace_identity)
        self.index_path = self.root / INDEX_NAME
        self.state_dir = self.root / STATE_DIR
        self.trash_dir = self.root / TRASH_DIR
        self.project_state_id = state_project_key(self.root)

    def ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "journal").mkdir(parents=True, exist_ok=True)
        self._recover_journal()

    def read_index(self) -> str:
        if not self.index_path.exists():
            return ""
        return self.index_path.read_text(encoding="utf-8-sig")

    def formatted_index(self) -> str:
        return format_index_for_context(
            self.read_index(),
            max_lines=self.config.index_max_lines,
            max_chars=self.config.index_max_chars,
        )

    def manifest(self, *, limit: int = 200) -> list[MemoryItem]:
        self.ensure_root()
        items: list[MemoryItem] = []
        for path in self.root.rglob("*.md"):
            if path.name == INDEX_NAME or TRASH_DIR in path.parts or STATE_DIR in path.parts:
                continue
            if path.is_symlink() or not path.is_file():
                continue
            stat = path.stat()
            doc = self._read_document(path)
            items.append(
                MemoryItem(
                    filename=path.relative_to(self.root).as_posix(),
                    name=doc.name,
                    description=doc.description,
                    memory_type=doc.memory_type,
                    mtime=stat.st_mtime,
                    path=path,
                )
            )
        items.sort(key=lambda item: item.mtime, reverse=True)
        return items[: max(0, limit)]

    def read(self, *, filename: str | None = None, name: str | None = None) -> tuple[MemoryItem, str]:
        item = self._find_item(filename=filename, name=name)
        text = item.path.read_text(encoding="utf-8-sig")
        return item, text

    def search(self, query: str, *, limit: int = 20, types: Iterable[str] | None = None) -> list[SearchResult]:
        needle = query.strip()
        if not needle:
            raise ValidationError("query 不能为空")
        # 按空白拆分多个词；任一词命中即返回，命中词数优先，其次比较总分。
        terms = tuple(dict.fromkeys(part.lower() for part in needle.split()))
        selected_types = {validate_type(value) for value in types} if types else None
        scored_results: list[tuple[int, int, SearchResult]] = []
        for item in self.manifest(limit=1000):
            if selected_types is not None and item.memory_type not in selected_types:
                continue
            text = item.path.read_text(encoding="utf-8-sig")
            name = (item.name or "").lower()
            description = (item.description or "").lower()
            body = text.lower()
            matched_terms = 0
            score = 0
            best_term = ""
            best_term_score = 0
            for term in terms:
                term_score = 0
                if term == name:
                    term_score += 20
                elif term in name:
                    term_score += 12
                if term in description:
                    term_score += 8
                term_score += min(body.count(term), 10)
                if term_score <= 0:
                    continue
                matched_terms += 1
                score += term_score
                if term_score > best_term_score:
                    best_term = term
                    best_term_score = term_score
            if matched_terms == 0:
                continue
            snippet = self._snippet(text, best_term)
            result = SearchResult(item.filename, item.name, item.description, item.memory_type, score, snippet)
            scored_results.append((matched_terms, score, result))
        scored_results.sort(key=lambda entry: (-entry[0], -entry[1], entry[2].filename))
        return [result for _, _, result in scored_results[: max(1, min(limit, 100))]]

    def write(
        self,
        *,
        action: str = "upsert",
        filename: str | None = None,
        name: str | None = None,
        description: str | None = None,
        memory_type: str | None = None,
        body: str | None = None,
        title: str | None = None,
        origin_session_id: str | None = None,
    ) -> dict[str, object]:
        self.ensure_root()
        action = action.strip().lower()
        if action not in {"create", "update", "upsert"}:
            raise ValidationError("action 必须是 create、update 或 upsert")
        if name is not None:
            name = validate_name(name)
        if memory_type is not None:
            memory_type = validate_type(memory_type)
        if description is None or not description.strip():
            raise ValidationError("description 不能为空")
        if body is None or not body.strip():
            raise ValidationError("body 不能为空")

        with self._project_lock():
            existing = self._resolve_existing_for_write(action, filename=filename, name=name)
            if existing is None and action == "update":
                raise ValidationError("update 目标不存在，请提供有效 filename 或 name")
            if existing is not None and action == "create":
                raise ValidationError("create 目标已存在，请改用 upsert 或 update")

            target = existing.path if existing else self._path_for_new(filename=filename, name=name, description=description)
            target_filename = target.relative_to(self.root).as_posix()
            if existing:
                old_text = target.read_text(encoding="utf-8-sig")
                old_doc = parse_memory_document(old_text, target_filename)
                final_name = name or old_doc.name
                final_type = memory_type or old_doc.memory_type
                if not final_name or not final_type:
                    raise ValidationError("更新已有记忆时必须能确定 name 和 type")
                expected = FileFingerprint.read(target)
                rendered = render_memory_document(
                    existing_text=old_text,
                    filename=target_filename,
                    name=final_name,
                    description=description,
                    memory_type=final_type,
                    body=body,
                    origin_session_id=origin_session_id,
                )
            else:
                expected = FileFingerprint(False)
                rendered = render_memory_document(
                    existing_text=None,
                    filename=target_filename,
                    name=name or "",
                    description=description,
                    memory_type=memory_type or "",
                    body=body,
                    origin_session_id=origin_session_id,
                )

            final_doc = parse_memory_document(rendered, target_filename)
            index_title = (title or final_doc.name or target.stem).strip()
            journal = self._create_journal(
                action="write",
                filename=target_filename,
                title=index_title,
                description=description,
            )
            atomic_write_text(target, rendered, expected=expected)
            self._update_index(target_filename, index_title, description)
            self._complete_journal(journal)
            return {
                "filename": target_filename,
                "created": existing is None,
                "name": final_doc.name,
                "type": final_doc.memory_type,
                "index_updated": True,
            }

    def forget(self, *, filename: str | None = None, name: str | None = None, reason: str | None = None) -> dict[str, object]:
        self.ensure_root()
        with self._project_lock():
            item = self._find_item(filename=filename, name=name)
            self.trash_dir.mkdir(parents=True, exist_ok=True)
            timestamp = utc_now_iso().replace(":", "").replace("-", "").replace("+", "").replace(".", "")
            trash_name = f"{timestamp}-{item.path.name}"
            trash_path = self.trash_dir / trash_name
            journal = self._create_journal(action="delete", filename=item.filename, title="", description=reason or "")
            os.replace(item.path, trash_path)
            self._remove_index(item.filename)
            self._complete_journal(journal)
            return {"deleted": True, "filename": item.filename, "trash_path": str(trash_path), "index_updated": True}

    def repair_index(self, *, dry_run: bool = True) -> dict[str, object]:
        self.ensure_root()
        with self._project_lock():
            items = self.manifest(limit=10000)
            current = self.read_index()
            existing_targets = target_filenames(current)
            actual = {item.filename: item for item in items}
            lines = current.splitlines()
            new_lines: list[str] = []
            seen: set[str] = set()
            changed = 0
            for line in lines:
                pointer = None
                from .indexing import parse_pointer

                pointer = parse_pointer(line, "")
                if pointer is None:
                    new_lines.append(line)
                    continue
                normalized = pointer.filename.replace("\\", "/")
                item = actual.get(normalized)
                if item is None:
                    changed += 1
                    continue
                replacement = pointer_line(item.name or item.path.stem, normalized, item.description or "")
                if replacement != line:
                    changed += 1
                new_lines.append(replacement)
                seen.add(normalized)
            for filename, item in sorted(actual.items()):
                if filename in seen:
                    continue
                changed += 1
                new_lines.append(pointer_line(item.name or item.path.stem, filename, item.description or ""))

            new_text = "\n".join(new_lines).rstrip() + "\n" if new_lines else ""
            removed = len(existing_targets - set(actual))
            added = len(set(actual) - existing_targets)
            if dry_run or new_text == current:
                return {"dry_run": dry_run, "changed": changed, "added": added, "removed": removed, "backup_path": None}

            backup_dir = self.state_dir / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup = backup_dir / f"MEMORY-{utc_now_iso().replace(':', '').replace('-', '')}.md"
            if current:
                atomic_write_text(backup, current)
            atomic_write_text(self.index_path, new_text, expected=FileFingerprint.read(self.index_path))
            return {"dry_run": False, "changed": changed, "added": added, "removed": removed, "backup_path": str(backup) if current else None}

    def status(self) -> dict[str, object]:
        self.ensure_root()
        items = self.manifest(limit=10000)
        queue_dir = self.config.state_root / "queue" / self.project_state_id
        pending = len(list(queue_dir.glob("*.json"))) if queue_dir.exists() else 0
        return {
            "backend": self.backend.name,
            "cli_storage_root": str(self.config.cli_storage_root),
            "project_root": str(self.root),
            "workspace_path": self.workspace_path,
            "item_count": len(items),
            "index_lines": len(self.read_index().splitlines()),
            "pending_extracts": pending,
            "auto_extract": self.config.auto_extract,
        }

    def _read_document(self, path: Path) -> MemoryDocument:
        text = ""
        try:
            with path.open("r", encoding="utf-8-sig") as handle:
                for _ in range(30):
                    line = handle.readline()
                    if line == "":
                        break
                    text += line
        except OSError:
            return MemoryDocument(filename=path.name)
        return parse_memory_document(text, path.name)

    def _find_item(self, *, filename: str | None = None, name: str | None = None) -> MemoryItem:
        items = self.manifest(limit=10000)
        if filename:
            normalized = validate_filename(filename)
            for item in items:
                if item.filename == normalized:
                    return item
            raise ValidationError(f"记忆不存在: {normalized}")
        if name:
            wanted = validate_name(name)
            matches = [item for item in items if item.name == wanted]
            if len(matches) == 1:
                return matches[0]
            if not matches:
                raise ValidationError(f"记忆不存在: {wanted}")
            raise ValidationError(f"name 对应多条记忆，请改用 filename: {wanted}")
        raise ValidationError("必须提供 filename 或 name")

    def _resolve_existing_for_write(self, action: str, *, filename: str | None, name: str | None) -> MemoryItem | None:
        try:
            return self._find_item(filename=filename, name=name)
        except ValidationError:
            if action in {"create", "upsert"}:
                return None
            raise

    def _path_for_new(self, *, filename: str | None, name: str | None, description: str) -> Path:
        if filename:
            relative = validate_filename(filename)
        else:
            base = validate_name(name) if name else self._slugify(description)
            relative = f"{base}.md"
        return self._contained_path(relative)

    def _contained_path(self, relative: str) -> Path:
        relative = validate_filename(relative)
        root_abs = os.path.abspath(self.root)
        target_abs = os.path.abspath(os.path.join(root_abs, *relative.split("/")))
        try:
            common = os.path.commonpath([root_abs, target_abs])
        except ValueError as exc:
            raise ValidationError("filename 越过记忆目录") from exc
        if common != root_abs:
            raise ValidationError("filename 越过记忆目录")
        target = Path(target_abs)
        cursor = target.parent
        while cursor != self.root and cursor != cursor.parent:
            if cursor.exists() and cursor.is_symlink():
                raise ValidationError("记忆目录不允许使用符号链接")
            cursor = cursor.parent
        if target.exists() and target.is_symlink():
            raise ValidationError("记忆文件不允许使用符号链接")
        return target

    def _slugify(self, value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:48]
        return slug or "memory"

    def _update_index(self, filename: str, title: str, description: str) -> None:
        current = self.read_index()
        updated = update_index_text(current, filename=filename, title=title, description=description)
        atomic_write_text(self.index_path, updated, expected=FileFingerprint.read(self.index_path))

    def _remove_index(self, filename: str) -> None:
        current = self.read_index()
        updated = remove_index_text(current, filename=filename)
        atomic_write_text(self.index_path, updated, expected=FileFingerprint.read(self.index_path))

    def _snippet(self, text: str, needle: str, *, width: int = 180) -> str:
        lower = text.lower()
        index = lower.find(needle.lower())
        if index < 0:
            return text.strip().replace("\n", " ")[:width]
        start = max(0, index - width // 3)
        return text[start : start + width].strip().replace("\n", " ")

    @contextmanager
    def _project_lock(self, *, timeout: float = 30.0, stale_after: float = 600.0) -> Iterator[None]:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        lock_dir = self.state_dir / "project.lock"
        deadline = time.monotonic() + timeout
        while True:
            try:
                lock_dir.mkdir()
                (lock_dir / "owner.json").write_text(json.dumps({"pid": os.getpid(), "time": utc_now_iso()}), encoding="utf-8")
                break
            except FileExistsError:
                try:
                    age = time.time() - lock_dir.stat().st_mtime
                except FileNotFoundError:
                    continue
                if age > stale_after:
                    shutil.rmtree(lock_dir, ignore_errors=True)
                    continue
                if time.monotonic() >= deadline:
                    raise LockError("等待记忆项目锁超时")
                time.sleep(0.1)
        try:
            yield
        finally:
            shutil.rmtree(lock_dir, ignore_errors=True)

    def _create_journal(self, *, action: str, filename: str, title: str, description: str) -> Path:
        journal_dir = self.state_dir / "journal"
        journal_dir.mkdir(parents=True, exist_ok=True)
        name = f"{int(time.time() * 1000)}-{os.getpid()}-{abs(hash(filename))}.json"
        path = journal_dir / name
        write_json(path, {"action": action, "filename": filename, "title": title, "description": description, "created_at": utc_now_iso()})
        return path

    def _complete_journal(self, path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def _recover_journal(self) -> None:
        journal_dir = self.state_dir / "journal"
        if not journal_dir.exists():
            return
        for path in journal_dir.glob("*.json"):
            try:
                payload = read_json(path)
            except Exception:
                continue
            filename = payload.get("filename")
            action = payload.get("action")
            if not isinstance(filename, str):
                self._complete_journal(path)
                continue
            target = self._contained_path(filename)
            if action == "write" and target.exists():
                self._update_index(filename, str(payload.get("title") or target.stem), str(payload.get("description") or ""))
            elif action == "delete":
                self._remove_index(filename)
            self._complete_journal(path)
