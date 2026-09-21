"""插件配置加载和环境变量覆盖。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .errors import ConfigError


DEFAULT_STATE_DIR = Path.home() / ".zcodex-memory"
DEFAULT_CONFIG_PATH = DEFAULT_STATE_DIR / "config.json"


@dataclass(frozen=True)
class Config:
    backend: str = "zcode-files"
    cli_storage_root: Path = Path.home() / ".zcode" / "cli"
    auto_extract: bool = True
    extract_model: str | None = None
    index_max_lines: int = 200
    index_max_chars: int = 12000
    source_path: Path | None = None

    @property
    def state_root(self) -> Path:
        if self.source_path is not None:
            return self.source_path.parent
        return DEFAULT_STATE_DIR

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "cli_storage_root": str(self.cli_storage_root),
            "auto_extract": self.auto_extract,
            "extract_model": self.extract_model,
            "index_max_lines": self.index_max_lines,
            "index_max_chars": self.index_max_chars,
        }


def _expand_path(value: str | os.PathLike[str]) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(os.fspath(value)))).absolute()


def _parse_bool(value: Any, *, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ConfigError(f"配置项 {field} 必须是布尔值")


def _parse_positive_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise ConfigError(f"配置项 {field} 必须是正整数")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"配置项 {field} 必须是正整数") from exc
    if parsed <= 0:
        raise ConfigError(f"配置项 {field} 必须是正整数")
    return parsed


def _load_json(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"无法读取配置文件 {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ConfigError(f"配置文件必须是 JSON 对象: {path}")
    return payload


def config_path_from_env() -> Path:
    override = os.environ.get("ZCODEX_MEMORY_CONFIG")
    if override:
        return _expand_path(override)
    return DEFAULT_CONFIG_PATH


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    source_path = _expand_path(path) if path is not None else config_path_from_env()
    payload = dict(_load_json(source_path))
    env = os.environ

    if "ZCODEX_MEMORY_BACKEND" in env:
        payload["backend"] = env["ZCODEX_MEMORY_BACKEND"]
    if "ZCODEX_MEMORY_CLI_STORAGE_ROOT" in env:
        payload["cli_storage_root"] = env["ZCODEX_MEMORY_CLI_STORAGE_ROOT"]
    if "ZCODEX_MEMORY_AUTO_EXTRACT" in env:
        payload["auto_extract"] = env["ZCODEX_MEMORY_AUTO_EXTRACT"]
    if "ZCODEX_MEMORY_MODEL" in env:
        payload["extract_model"] = env["ZCODEX_MEMORY_MODEL"] or None

    backend = str(payload.get("backend", "zcode-files")).strip()
    if not backend:
        raise ConfigError("配置项 backend 不能为空")

    storage = payload.get("cli_storage_root", Path.home() / ".zcode" / "cli")
    if not isinstance(storage, (str, os.PathLike)):
        raise ConfigError("配置项 cli_storage_root 必须是路径字符串")

    model = payload.get("extract_model")
    if model is not None and not isinstance(model, str):
        raise ConfigError("配置项 extract_model 必须是字符串或 null")
    if isinstance(model, str):
        model = model.strip() or None

    return Config(
        backend=backend,
        cli_storage_root=_expand_path(storage),
        auto_extract=_parse_bool(payload.get("auto_extract", True), field="auto_extract"),
        extract_model=model,
        index_max_lines=_parse_positive_int(payload.get("index_max_lines", 200), field="index_max_lines"),
        index_max_chars=_parse_positive_int(payload.get("index_max_chars", 12000), field="index_max_chars"),
        source_path=source_path,
    )
