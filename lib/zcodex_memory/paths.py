"""ZCode 项目记忆路径算法。

改编说明：
本文件的项目记忆路径规则参考并移植自 ZCode 上游项目：
https://github.com/zai-org/ZCode/blob/main/apps/zcode-cli/packages/core/src/memory/project-root.ts
上游项目采用 Apache-2.0 许可证。
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path


_SLUG_PATTERN = re.compile(r"[^a-z0-9._-]+")


def normalize_workspace_path(workspace_path: str | os.PathLike[str]) -> str:
    """按 Node path.resolve 的语义规范化，但不解析 symlink/junction。"""

    return os.path.abspath(os.path.normpath(os.fspath(workspace_path)))


def sanitize_project_slug(value: str) -> str:
    slug = _SLUG_PATTERN.sub("-", value.lower()).strip("-.")[:48]
    return slug or "project"


def project_key(workspace_path: str | os.PathLike[str], workspace_identity: str | None = None) -> tuple[str, str]:
    normalized = normalize_workspace_path(workspace_path)
    identity = workspace_identity.strip() if workspace_identity and workspace_identity.strip() else None
    key_source = identity or (normalized.lower() if os.name == "nt" else normalized)
    digest = hashlib.sha256(key_source.encode("utf-8")).hexdigest()[:16]
    basename = os.path.basename(normalized.rstrip("\\/")) or "project"
    slug = "project" if identity else sanitize_project_slug(basename)
    return slug, digest


def resolve_project_memory_root(
    cli_storage_root: str | os.PathLike[str],
    workspace_path: str | os.PathLike[str],
    workspace_identity: str | None = None,
) -> Path:
    slug, digest = project_key(workspace_path, workspace_identity)
    return Path(cli_storage_root) / "memories" / "projects" / f"{slug}-{digest}" / "memory"


def state_project_key(root: Path) -> str:
    normalized = str(root).replace("\\", "/")
    if os.name == "nt":
        normalized = normalized.lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
