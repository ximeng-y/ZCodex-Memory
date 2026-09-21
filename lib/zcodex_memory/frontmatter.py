"""ZCodex Memory frontmatter 的最小安全解析与更新。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .errors import ValidationError


TYPE_VALUES = ("user", "feedback", "project", "reference")
_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$|^[a-z0-9]$")


@dataclass
class MemoryDocument:
    filename: str
    name: str | None = None
    description: str | None = None
    memory_type: str | None = None
    node_type: str | None = None
    origin_session_id: str | None = None
    body: str = ""
    raw_text: str = ""
    has_frontmatter: bool = False
    bom: bool = False
    newline: str = "\n"

    @property
    def title(self) -> str:
        return self.name or Path(self.filename).stem


def validate_name(name: str) -> str:
    value = name.strip()
    if not _NAME_PATTERN.fullmatch(value):
        raise ValidationError("记忆 name 必须是小写 kebab-case，长度 1-64")
    return value


def validate_type(memory_type: str) -> str:
    value = memory_type.strip()
    if value not in TYPE_VALUES:
        raise ValidationError(f"记忆 type 必须是 {', '.join(TYPE_VALUES)}")
    return value


def _unquote(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        inner = text[1:-1]
        if text[0] == '"':
            return inner.replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\')
        return inner.replace("''", "'")
    return text


def _quote(value: str) -> str:
    if value == "" or value.strip() != value or any(char in value for char in ':#[]{}",&*!|>%@`'):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def _split_lines(text: str) -> tuple[str, list[str]]:
    newline = "\r\n" if "\r\n" in text else "\n"
    return newline, text.splitlines()


def _find_frontmatter(lines: list[str]) -> tuple[int, int] | None:
    if not lines or lines[0].strip() != "---":
        return None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return 0, index
    return None


def parse_memory_document(text: str, filename: str) -> MemoryDocument:
    bom = text.startswith("\ufeff")
    raw = text[1:] if bom else text
    newline, lines = _split_lines(raw)
    doc = MemoryDocument(filename=filename, raw_text=raw, bom=bom, newline=newline)
    bounds = _find_frontmatter(lines)
    if bounds is None:
        doc.body = raw.strip()
        return doc

    start, end = bounds
    doc.has_frontmatter = True
    metadata_indent: int | None = None
    for raw_line in lines[start + 1 : end]:
        if not raw_line.strip():
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if metadata_indent is not None and indent > metadata_indent:
            if key == "type":
                doc.memory_type = _unquote(value) or None
            elif key == "node_type":
                doc.node_type = _unquote(value) or None
            elif key == "originSessionId":
                doc.origin_session_id = _unquote(value) or None
            continue
        metadata_indent = indent if key == "metadata" else None
        if key == "name":
            doc.name = _unquote(value) or None
        elif key == "description":
            doc.description = _unquote(value) or None
        elif key == "type":
            doc.memory_type = _unquote(value) or None

    body_lines = lines[end + 1 :]
    if body_lines and body_lines[0].strip() == "":
        body_lines = body_lines[1:]
    doc.body = "\n".join(body_lines).strip()
    return doc


def _set_scalar(lines: list[str], key: str, value: str) -> None:
    pattern = re.compile(rf"^{re.escape(key)}\s*:")
    for index, line in enumerate(lines):
        if pattern.match(line):
            lines[index] = f"{key}: {_quote(value)}"
            return
    insert_at = next((i for i, line in enumerate(lines) if line.strip() == "metadata:"), len(lines))
    lines.insert(insert_at, f"{key}: {_quote(value)}")


def _set_metadata(lines: list[str], key: str, value: str) -> None:
    metadata_index = next((i for i, line in enumerate(lines) if line.strip() == "metadata:"), None)
    if metadata_index is None:
        lines.extend(["metadata:", f"  {key}: {_quote(value)}"])
        return

    block_end = len(lines)
    for index in range(metadata_index + 1, len(lines)):
        line = lines[index]
        if line.strip() and not line.startswith((" ", "\t")):
            block_end = index
            break
    pattern = re.compile(rf"^\s+{re.escape(key)}\s*:")
    for index in range(metadata_index + 1, block_end):
        if pattern.match(lines[index]):
            lines[index] = f"  {key}: {_quote(value)}"
            return
    lines.insert(block_end, f"  {key}: {_quote(value)}")


def render_memory_document(
    *,
    existing_text: str | None,
    filename: str,
    name: str,
    description: str,
    memory_type: str,
    body: str,
    origin_session_id: str | None = None,
) -> str:
    name = validate_name(name)
    description = description.strip()
    memory_type = validate_type(memory_type)
    body = body.strip()
    if not description:
        raise ValidationError("description 不能为空")
    if not body:
        raise ValidationError("body 不能为空")

    if not existing_text:
        lines = [
            "---",
            f"name: {_quote(name)}",
            f"description: {_quote(description)}",
            "metadata:",
            "  node_type: memory",
            f"  type: {_quote(memory_type)}",
        ]
        if origin_session_id:
            lines.append(f"  originSessionId: {_quote(origin_session_id)}")
        lines.extend(["---", "", body, ""])
        return "\n".join(lines)

    bom = existing_text.startswith("\ufeff")
    raw = existing_text[1:] if bom else existing_text
    newline, lines = _split_lines(raw)
    bounds = _find_frontmatter(lines)
    if bounds is None:
        front = [
            "---",
            f"name: {_quote(name)}",
            f"description: {_quote(description)}",
            "metadata:",
            "  node_type: memory",
            f"  type: {_quote(memory_type)}",
        ]
        if origin_session_id:
            front.append(f"  originSessionId: {_quote(origin_session_id)}")
        front.extend(["---", ""])
        result = front + raw.splitlines() if raw.strip() else front + [body]
        return ("\ufeff" if bom else "") + newline.join(result) + newline

    _, end = bounds
    front_lines = lines[1:end]
    _set_scalar(front_lines, "name", name)
    _set_scalar(front_lines, "description", description)
    _set_metadata(front_lines, "type", memory_type)
    if origin_session_id:
        _set_metadata(front_lines, "originSessionId", origin_session_id)
    new_lines = ["---", *front_lines, "---", "", *body.splitlines()]
    return ("\ufeff" if bom else "") + newline.join(new_lines) + newline


def document_summary(text: str, filename: str) -> MemoryDocument:
    return parse_memory_document(text, filename)
