#!/usr/bin/env python3
"""Stop Hook：异步触发后台记忆提取。"""

from __future__ import annotations

from _common import emit, extractor_guard, is_short_prompt, load_config_safe, log, queue_snapshot, read_event, store_from_event
from zcodex_memory.extraction import drain_queue
from zcodex_memory.session_state import delete_turn, read_turn


def main() -> int:
    if extractor_guard():
        return 0
    event = read_event()
    if event.get("stop_hook_active") is True:
        emit({"continue": True})
        return 0
    config, _ = load_config_safe()
    if config is None:
        emit({"continue": True})
        return 0
    if not config.auto_extract:
        emit({"continue": True})
        return 0
    session_id = str(event.get("session_id") or "")
    turn_id = str(event.get("turn_id") or "")
    state = read_turn(config, session_id=session_id, turn_id=turn_id)
    if state is None:
        emit({"continue": True})
        return 0
    try:
        if state.direct_write or is_short_prompt(state.prompt):
            delete_turn(config, session_id=session_id, turn_id=turn_id)
            emit({"continue": True})
            return 0
        store = store_from_event({**event, "cwd": state.cwd}, config)
        queue_snapshot(event, config, state, store)
        result = drain_queue(config=config)
        log(config, f"Stop 提取完成: {result}")
    except Exception as exc:
        log(config, f"Stop 提取失败: {type(exc).__name__}: {exc}")
    emit({"continue": True})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
