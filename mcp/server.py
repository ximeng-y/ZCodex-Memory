#!/usr/bin/env python3
"""ZCodex Memory MCP stdio 启动入口。"""

from __future__ import annotations

import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "lib"))

from zcodex_memory.mcp_protocol import main


if __name__ == "__main__":
    raise SystemExit(main())
