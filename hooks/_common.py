"""Hook 脚本共用工具。"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "lib"))

from zcodex_memory.config import Config, load_config
from zcodex_memory.errors import ConfigError, ZCodexMemoryError
from zcodex_memory.session_state import TurnState, capture_prompt, delete_turn, enqueue_snapshot, mark_direct_write, read_turn
from zcodex_memory.store import ProjectMemoryStore
from zcodex_memory.util import append_log


EXPLICIT_REMEMBER = re.compile(r"(记住|记下|牢记|remember\s+(?:that\s+)?|please\s+remember)", re.IGNORECASE)
EXPLICIT_FORGET = re.compile(r"(忘掉|忘记|不要再记住|forget\s+|please\s+forget)", re.IGNORECASE)
CJK_PATTERN = re.compile(r"[\u3400-\u9fff]")


def extractor_guard() -> bool:
    return os.environ.get("CODEX_ZCODEX_MEMORY_EXTRACTOR") == "1"


def read_event() -> dict[str, Any]:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def log(config: Config, message: str, *, name: str = "hooks.log") -> None:
    append_log(config.state_root / "logs" / name, message)


def load_config_safe() -> tuple[Config | None, str | None]:
    try:
        return load_config(), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def store_from_event(event: dict[str, Any], config: Config) -> ProjectMemoryStore:
    cwd = str(event.get("cwd") or os.getcwd())
    return ProjectMemoryStore(config, cwd, os.environ.get("ZCODEX_WORKSPACE_IDENTITY"))


def explicit_intent(prompt: str) -> str | None:
    if EXPLICIT_FORGET.search(prompt):
        return "forget"
    if EXPLICIT_REMEMBER.search(prompt):
        return "remember"
    return None


def is_short_prompt(prompt: str) -> bool:
    text = prompt.strip()
    if not text:
        return True
    if CJK_PATTERN.search(text):
        return len(text) < 6
    return len(text.split()) < 3


def response_failed(response: Any) -> bool:
    if isinstance(response, dict):
        if response.get("isError") is True or response.get("is_error") is True:
            return True
        return any(response_failed(value) for value in response.values())
    if isinstance(response, list):
        return any(response_failed(value) for value in response)
    return False


def capture_from_event(event: dict[str, Any], config: Config) -> TurnState:
    return capture_prompt(
        config,
        session_id=str(event.get("session_id") or ""),
        turn_id=str(event.get("turn_id") or ""),
        cwd=str(event.get("cwd") or os.getcwd()),
        prompt=str(event.get("prompt") or ""),
        explicit_intent=explicit_intent(str(event.get("prompt") or "")),
        workspace_identity=os.environ.get("ZCODEX_WORKSPACE_IDENTITY"),
    )


def mark_event_direct_write(event: dict[str, Any], config: Config) -> TurnState | None:
    return mark_direct_write(
        config,
        session_id=str(event.get("session_id") or ""),
        turn_id=str(event.get("turn_id") or ""),
    )


def queue_snapshot(event: dict[str, Any], config: Config, state: TurnState, store: ProjectMemoryStore) -> Path:
    snapshot = {
        "session_id": state.session_id,
        "turn_id": state.turn_id,
        "cwd": state.cwd,
        "prompt": state.prompt,
        "assistant_message": event.get("last_assistant_message") or "",
        "model": event.get("model") or "",
        "captured_at": state.captured_at,
        "workspace_identity": state.workspace_identity,
    }
    return enqueue_snapshot(config, project_state_id=store.project_state_id, session_id=state.session_id, turn_id=state.turn_id, snapshot=snapshot)
