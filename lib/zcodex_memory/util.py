"""通用文件、JSON 和日志工具。"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class FileFingerprint:
    """用于检测文件是否在读写间变化。"""

    exists: bool
    size: int = 0
    mtime_ns: int = 0

    @classmethod
    def read(cls, path: Path) -> "FileFingerprint":
        try:
            stat = path.stat()
        except FileNotFoundError:
            return cls(False)
        return cls(True, stat.st_size, stat.st_mtime_ns)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def atomic_write_text(
    path: Path,
    content: str,
    *,
    expected: FileFingerprint | None = None,
    encoding: str = "utf-8",
) -> None:
    atomic_write_bytes(path, content.encode(encoding), expected=expected)


def atomic_write_bytes(
    path: Path,
    content: bytes,
    *,
    expected: FileFingerprint | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if expected is not None and FileFingerprint.read(path) != expected:
        from .errors import ConflictError

        raise ConflictError(f"文件已被其他进程修改: {path}")

    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def append_log(path: Path, message: str, *, max_bytes: int = 2 * 1024 * 1024) -> None:
    """写入 UTF-8 日志；仅做轻量轮转，不向 stdout 输出。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.exists() and path.stat().st_size > max_bytes:
            rotated = path.with_suffix(path.suffix + ".1")
            try:
                rotated.unlink()
            except FileNotFoundError:
                pass
            os.replace(path, rotated)
    except OSError:
        pass

    line = f"[{utc_now_iso()}] {message.rstrip()}\n"
    try:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
    except OSError:
        pass


def compact_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def sleep_short() -> None:
    time.sleep(0.05)
