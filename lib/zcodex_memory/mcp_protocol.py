"""最小 MCP stdio JSON-RPC 服务端。"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, TextIO

from .config import load_config
from .errors import ZCodexMemoryError
from .store import ProjectMemoryStore


PROTOCOL_VERSION = "2025-06-18"


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "memory_status",
        "description": "查看当前项目记忆后端、路径、条目数和待提取任务数。",
        "inputSchema": {
            "type": "object",
            "properties": {"project_root": {"type": "string", "description": "当前项目绝对路径"}},
            "required": ["project_root"],
            "additionalProperties": False,
        },
    },
    {
        "name": "memory_index",
        "description": "读取当前项目的 MEMORY.md 索引内容。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_root": {"type": "string"},
                "max_lines": {"type": "integer", "minimum": 1},
                "max_chars": {"type": "integer", "minimum": 1},
            },
            "required": ["project_root"],
            "additionalProperties": False,
        },
    },
    {
        "name": "memory_manifest",
        "description": "列出记忆文件及其 name、description、type 和修改时间。",
        "inputSchema": {
            "type": "object",
            "properties": {"project_root": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 1000}},
            "required": ["project_root"],
            "additionalProperties": False,
        },
    },
    {
        "name": "memory_search",
        "description": "按空白拆分多个查询词，对 name、description 和正文做确定性词法搜索；任一词命中即返回，不使用向量检索。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_root": {"type": "string"},
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                "types": {"type": "array", "items": {"type": "string", "enum": ["user", "feedback", "project", "reference"]}},
            },
            "required": ["project_root", "query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "memory_read",
        "description": "按 filename 或 name 读取一条完整记忆。",
        "inputSchema": {
            "type": "object",
            "properties": {"project_root": {"type": "string"}, "filename": {"type": "string"}, "name": {"type": "string"}},
            "required": ["project_root"],
            "additionalProperties": False,
        },
    },
    {
        "name": "memory_write",
        "description": "创建、更新或 upsert 一条记忆，并维护 MEMORY.md 索引。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_root": {"type": "string"},
                "action": {"type": "string", "enum": ["create", "update", "upsert"]},
                "filename": {"type": "string"},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "type": {"type": "string", "enum": ["user", "feedback", "project", "reference"]},
                "body": {"type": "string"},
                "title": {"type": "string"},
                "origin_session_id": {"type": "string"},
            },
            "required": ["project_root", "action", "description", "body"],
            "additionalProperties": False,
        },
    },
    {
        "name": "memory_forget",
        "description": "把一条记忆移入 .trash，并删除对应索引指针。",
        "inputSchema": {
            "type": "object",
            "properties": {"project_root": {"type": "string"}, "filename": {"type": "string"}, "name": {"type": "string"}, "reason": {"type": "string"}},
            "required": ["project_root"],
            "additionalProperties": False,
        },
    },
    {
        "name": "memory_repair_index",
        "description": "校验并修复 MEMORY.md 指针；默认只 dry-run。",
        "inputSchema": {
            "type": "object",
            "properties": {"project_root": {"type": "string"}, "dry_run": {"type": "boolean"}},
            "required": ["project_root"],
            "additionalProperties": False,
        },
    },
]


def _json_text(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _tool_result(payload: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": _json_text(payload)}], "isError": False}


def _tool_error(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


class MCPProtocolServer:
    def __init__(self, *, stdout: TextIO, stderr: TextIO) -> None:
        self.stdout = stdout
        self.stderr = stderr

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params") if isinstance(request.get("params"), dict) else {}
        if method == "notifications/initialized" or method == "notifications/cancelled":
            return None
        if method == "initialize":
            return self._response(request_id, {
                "protocolVersion": params.get("protocolVersion") or PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "zcodex_memory", "version": "1.0.0"},
                "instructions": "所有项目记忆工具都必须传入当前工作区的绝对路径 project_root。",
            })
        if method == "ping":
            return self._response(request_id, {})
        if method == "tools/list":
            return self._response(request_id, {"tools": TOOL_DEFINITIONS})
        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            if not isinstance(name, str):
                return self._response(request_id, _tool_error("缺少 MCP 工具名"))
            try:
                return self._response(request_id, _tool_result(self._call_tool(name, arguments)))
            except Exception as exc:
                return self._response(request_id, _tool_error(f"{type(exc).__name__}: {exc}"))
        if request_id is None:
            return None
        return self._error(request_id, -32601, f"不支持的方法: {method}")

    def _call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if os.environ.get("CODEX_ZCODEX_MEMORY_EXTRACTOR") == "1" and name in {"memory_write", "memory_forget", "memory_repair_index"}:
            raise ValueError("后台提取进程禁止调用 Memory 写工具")
        project_root = arguments.get("project_root")
        if not isinstance(project_root, str) or not project_root.strip():
            raise ValueError("project_root 必须是当前项目的绝对路径")
        config = load_config()
        store = ProjectMemoryStore(config, project_root, os.environ.get("ZCODEX_WORKSPACE_IDENTITY"))
        if name == "memory_status":
            return store.status()
        if name == "memory_index":
            text = store.read_index()
            max_lines = int(arguments.get("max_lines") or config.index_max_lines)
            max_chars = int(arguments.get("max_chars") or config.index_max_chars)
            from .indexing import format_index_for_context

            return {"content": format_index_for_context(text, max_lines=max_lines, max_chars=max_chars), "full_path": str(store.index_path)}
        if name == "memory_manifest":
            return {"items": [self._item_dict(item) for item in store.manifest(limit=int(arguments.get("limit") or 200))]}
        if name == "memory_search":
            return {"results": [self._search_dict(item) for item in store.search(str(arguments.get("query") or ""), limit=int(arguments.get("limit") or 20), types=arguments.get("types"))]}
        if name == "memory_read":
            item, content = store.read(filename=arguments.get("filename"), name=arguments.get("name"))
            return {"item": self._item_dict(item), "content": content}
        if name == "memory_write":
            return store.write(
                action=str(arguments.get("action") or "upsert"),
                filename=arguments.get("filename"),
                name=arguments.get("name"),
                description=arguments.get("description"),
                memory_type=arguments.get("type"),
                body=arguments.get("body"),
                title=arguments.get("title"),
                origin_session_id=arguments.get("origin_session_id"),
            )
        if name == "memory_forget":
            return store.forget(filename=arguments.get("filename"), name=arguments.get("name"), reason=arguments.get("reason"))
        if name == "memory_repair_index":
            return store.repair_index(dry_run=bool(arguments.get("dry_run", True)))
        raise ValueError(f"未知工具: {name}")

    def _response(self, request_id: Any, result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _error(self, request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    def _item_dict(self, item) -> dict[str, Any]:
        return {
            "filename": item.filename,
            "name": item.name,
            "description": item.description,
            "type": item.memory_type,
            "mtime": item.mtime,
        }

    def _search_dict(self, item) -> dict[str, Any]:
        return {
            "filename": item.filename,
            "name": item.name,
            "description": item.description,
            "type": item.memory_type,
            "score": item.score,
            "snippet": item.snippet,
        }


def serve(stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout, stderr: TextIO = sys.stderr) -> int:
    server = MCPProtocolServer(stdout=stdout, stderr=stderr)
    for raw_line in stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("JSON-RPC 请求必须是对象")
            response = server.handle(request)
        except Exception as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"解析失败: {exc}"}}
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()
    return 0


def main() -> int:
    return serve()
