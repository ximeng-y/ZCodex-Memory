"""Session/Turn 临时状态与提取队列。"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import Config
from .util import read_json, utc_now_iso, write_json


_ID_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass
class TurnState:
    session_id: str
    turn_id: str
    cwd: str
    prompt: str
    captured_at: str
    direct_write: bool = False
    explicit_intent: str | None = None
    workspace_identity: str | None = None

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "TurnState":
        return cls(
            session_id=str(payload.get("session_id", "")),
            turn_id=str(payload.get("turn_id", "")),
            cwd=str(payload.get("cwd", "")),
            prompt=str(payload.get("prompt", "")),
            captured_at=str(payload.get("captured_at", "")),
            direct_write=bool(payload.get("direct_write", False)),
            explicit_intent=payload.get("explicit_intent") if isinstance(payload.get("explicit_intent"), str) else None,
            workspace_identity=payload.get("workspace_identity") if isinstance(payload.get("workspace_identity"), str) else None,
        )


def _safe_id(value: str) -> str:
    cleaned = _ID_PATTERN.sub("-", value.strip()).strip("-")
    return cleaned[:160] or "unknown"


def sessions_root(config: Config) -> Path:
    return config.state_root / "sessions"


def queue_root(config: Config) -> Path:
    return config.state_root / "queue"


def turn_path(config: Config, session_id: str, turn_id: str) -> Path:
    return sessions_root(config) / _safe_id(session_id) / f"{_safe_id(turn_id)}.json"


def capture_prompt(config: Config, *, session_id: str, turn_id: str, cwd: str, prompt: str, explicit_intent: str | None = None, workspace_identity: str | None = None) -> TurnState:
    state = TurnState(
        session_id=session_id,
        turn_id=turn_id,
        cwd=cwd,
        prompt=prompt[:16000],
        captured_at=utc_now_iso(),
        direct_write=False,
        explicit_intent=explicit_intent,
        workspace_identity=workspace_identity,
    )
    write_json(turn_path(config, session_id, turn_id), asdict(state))
    return state


def read_turn(config: Config, *, session_id: str, turn_id: str) -> TurnState | None:
    path = turn_path(config, session_id, turn_id)
    if not path.exists():
        return None
    try:
        return TurnState.from_mapping(read_json(path))
    except Exception:
        return None


def mark_direct_write(config: Config, *, session_id: str, turn_id: str) -> TurnState | None:
    state = read_turn(config, session_id=session_id, turn_id=turn_id)
    if state is None:
        return None
    state.direct_write = True
    write_json(turn_path(config, session_id, turn_id), asdict(state))
    return state


def delete_turn(config: Config, *, session_id: str, turn_id: str) -> None:
    try:
        turn_path(config, session_id, turn_id).unlink()
    except FileNotFoundError:
        pass


def enqueue_snapshot(config: Config, *, project_state_id: str, session_id: str, turn_id: str, snapshot: dict[str, Any]) -> Path:
    path = queue_root(config) / project_state_id / f"{_safe_id(session_id)}-{_safe_id(turn_id)}.json"
    write_json(path, snapshot)
    return path


def list_pending(config: Config, *, project_state_id: str) -> list[Path]:
    directory = queue_root(config) / project_state_id
    if not directory.exists():
        return []
    return sorted(directory.glob("*.json"))


def read_snapshot(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    return payload if isinstance(payload, dict) else {}


def complete_snapshot(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def cleanup_stale(config: Config, *, max_age_seconds: float = 7 * 24 * 3600) -> int:
    removed = 0
    cutoff = time.time() - max_age_seconds
    for base in (sessions_root(config), queue_root(config)):
        if not base.exists():
            continue
        for path in base.rglob("*.json"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except FileNotFoundError:
                continue
    return removed
