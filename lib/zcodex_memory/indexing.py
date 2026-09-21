"""MEMORY.md 索引格式化与指针维护。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import ValidationError


LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+\.md)\)")
LEADING_FRONTMATTER_PATTERN = re.compile(r"^---\s*\n.*?^---\s*\n?", re.MULTILINE | re.DOTALL)


@dataclass(frozen=True)
class IndexPointer:
    filename: str
    title: str
    description: str
    line: str


def parse_pointer(line: str, label: str) -> IndexPointer | None:
    match = LINK_PATTERN.search(line)
    if not match:
        return None
    filename = match.group(1).strip()
    title_match = re.search(r"\[([^\]]+)\]", line)
    title = title_match.group(1) if title_match else filename
    separator = "—" if "—" in line else "-" if " - " in line else None
    description = ""
    if separator:
        description = line.split(separator, 1)[1].strip()
    return IndexPointer(filename=filename, title=title, description=description, line=label)


def pointer_line(title: str, filename: str, description: str) -> str:
    clean_title = title.strip() or filename.rsplit(".", 1)[0]
    clean_filename = filename.replace("\\", "/").lstrip("/")
    clean_description = description.strip().replace("\r", " ").replace("\n", " ")
    return f"- [{clean_title}]({clean_filename}) — {clean_description}".rstrip()


def update_index_text(text: str, *, filename: str, title: str, description: str) -> str:
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    replacement = pointer_line(title, filename, description)
    for index, line in enumerate(lines):
        pointer = parse_pointer(line, str(index))
        if pointer and pointer.filename.replace("\\", "/") == filename.replace("\\", "/"):
            lines[index] = replacement
            return newline.join(lines) + newline
    while lines and not lines[-1].strip():
        lines.pop()
    if lines:
        lines.append(replacement)
    else:
        lines = ["# Memory Index", "", replacement]
    return newline.join(lines) + newline


def remove_index_text(text: str, *, filename: str) -> str:
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    kept: list[str] = []
    for line in lines:
        pointer = parse_pointer(line, "")
        if pointer and pointer.filename.replace("\\", "/") == filename.replace("\\", "/"):
            continue
        kept.append(line)
    return newline.join(kept).rstrip() + newline


def format_index_for_context(text: str, *, max_lines: int, max_chars: int) -> str:
    without_frontmatter = LEADING_FRONTMATTER_PATTERN.sub("", text)
    trimmed = without_frontmatter.strip()
    if not trimmed:
        return ""
    lines = trimmed.splitlines()
    line_truncated = len(lines) > max_lines
    char_truncated = len(trimmed) > max_chars
    if not line_truncated and not char_truncated:
        return trimmed

    truncated = "\n".join(lines[:max_lines]) if line_truncated else trimmed
    if len(truncated) > max_chars:
        cut = truncated.rfind("\n", 0, max_chars)
        truncated = truncated[: cut if cut > 0 else max_chars]
    suffix = (
        f"\n\n> WARNING: MEMORY.md 超过注入预算（{len(lines)} 行，{len(trimmed)} 字符）。"
        " 这里只加载了部分索引；需要时使用 memory_search 查找完整内容。"
    )
    return truncated + suffix


def target_filenames(text: str) -> set[str]:
    targets: set[str] = set()
    for line in text.splitlines():
        pointer = parse_pointer(line, "")
        if pointer:
            targets.add(pointer.filename.replace("\\", "/"))
    return targets


def validate_filename(filename: str) -> str:
    value = filename.strip().replace("\\", "/")
    if not value:
        raise ValidationError("filename 不能为空")
    if value.startswith("/") or value.startswith("../") or "/../" in value or value == "..":
        raise ValidationError("filename 必须是记忆目录内的相对路径")
    if not value.lower().endswith(".md"):
        raise ValidationError("filename 必须以 .md 结尾")
    if value.lower().endswith("/memory.md") or value.lower() == "memory.md":
        raise ValidationError("MEMORY.md 只能由索引维护逻辑修改")
    return value
