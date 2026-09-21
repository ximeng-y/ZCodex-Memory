#!/usr/bin/env python3
"""PostToolUse Hook：记录当前回合已直接操作 Memory。"""

from __future__ import annotations

from _common import extractor_guard, load_config_safe, log, mark_event_direct_write, read_event, response_failed


TARGET_TOOLS = {
    "mcp__zcodex_memory__memory_write",
    "mcp__zcodex_memory__memory_forget",
    "mcp__zcodex_memory__memory_repair_index",
}


def main() -> int:
    if extractor_guard():
        return 0
    event = read_event()
    if str(event.get("tool_name") or "") not in TARGET_TOOLS:
        return 0
    if response_failed(event.get("tool_response")):
        return 0
    config, _ = load_config_safe()
    if config is None:
        return 0
    try:
        mark_event_direct_write(event, config)
    except Exception as exc:
        log(config, f"PostToolUse 失败: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
