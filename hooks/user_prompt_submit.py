#!/usr/bin/env python3
"""UserPromptSubmit Hook：保存本轮 prompt 并提示显式记忆操作。"""

from __future__ import annotations

from _common import capture_from_event, emit, explicit_intent, extractor_guard, load_config_safe, log, read_event


def main() -> int:
    if extractor_guard():
        return 0
    event = read_event()
    config, error = load_config_safe()
    if config is None:
        return 0
    try:
        state = capture_from_event(event, config)
        intent = explicit_intent(state.prompt)
        if intent == "remember":
            project_root = state.cwd.replace('"', '\"')
            context = (
                f"用户明确要求记住信息。你必须调用 `mcp__zcodex_memory__memory_write` 并传 `project_root='{project_root}'`；"
                "先搜索是否已有同义记忆，存在则 update，不存在才 create。"
            )
            emit({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context}})
        elif intent == "forget":
            project_root = state.cwd.replace('"', '\"')
            context = (
                f"用户明确要求忘掉信息。你必须先 `memory_search`，再用 `mcp__zcodex_memory__memory_forget` 删除明确目标，"
                f"并传 `project_root='{project_root}'`。匹配多条时先向用户澄清，不要批量删除。"
            )
            emit({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context}})
        return 0
    except Exception as exc:
        log(config, f"UserPromptSubmit 失败: {type(exc).__name__}: {exc}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
