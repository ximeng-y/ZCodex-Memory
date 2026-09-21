#!/usr/bin/env python3
"""SessionStart Hook：注入 MEMORY.md 索引。"""

from __future__ import annotations

import sys

from _common import emit, extractor_guard, load_config_safe, log, read_event, store_from_event


def main() -> int:
    if extractor_guard():
        return 0
    event = read_event()
    config, error = load_config_safe()
    if config is None:
        emit({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": f"ZCodex Memory 配置错误：{error}"}})
        return 0
    try:
        store = store_from_event(event, config)
        store.ensure_root()
        index = store.formatted_index()
        status = store.status()
        project_root = str(event.get("cwd") or store.workspace_path)
        context = [
            "# ZCodex Memory",
            "",
            f"项目记忆目录：`{store.root}`",
            f"调用 MCP 时必须传 `project_root='{project_root}'`。",
            "",
            "当任务可能涉及项目约束、用户偏好或历史决策时，先用 `memory_search` / `memory_read`，不要盲目假设。",
            "用户明确说“记住/忘掉”时，必须在回答或结束前调用 `memory_write` / `memory_forget`。",
            "一条记忆一个文件；`MEMORY.md` 只是索引。feed back/project 记忆优先包含 `**Why:**` 和 `**How to apply:**`。",
        ]
        if status.get("pending_extracts"):
            context.append("")
            context.append(f"当前有 {status['pending_extracts']} 个待重试的后台提取任务。")
        if index:
            context.extend(["", "## MEMORY.md", "", index])
        else:
            context.extend(["", "当前项目还没有记忆索引。"])
        text = "\n".join(context)
        if len(text) > config.index_max_chars:
            text = text[: config.index_max_chars] + "\n\n[ZCodex Memory 上下文已按预算截断]"
        emit({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}})
        return 0
    except Exception as exc:
        log(config, f"SessionStart 失败: {type(exc).__name__}: {exc}")
        emit({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": f"ZCodex Memory 读取失败：{type(exc).__name__}: {exc}"}})
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
