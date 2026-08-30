"""MCP result compatibility helpers."""

from __future__ import annotations

import json
from typing import Any

from mcp.types import CallToolResult, TextContent


def to_mcp_result(payload: dict[str, Any]) -> CallToolResult:
    """Return structured content plus a JSON text fallback for older clients."""
    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text=json.dumps(payload, ensure_ascii=False),
            )
        ],
        structuredContent=payload,
        isError=payload.get("status") == "error",
    )
