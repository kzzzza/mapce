"""MCP server implementation owned by the singleton MAPCE service."""

from __future__ import annotations

import json

from mcp.server import Server
from mcp.types import TextContent, Tool

from mapce.application import ToolDispatcher

from .tools import TOOL_DEFINITIONS


def create_backend_mcp_server(dispatcher: ToolDispatcher) -> Server:
    server = Server("mapce")

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        return TOOL_DEFINITIONS

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
        result = await dispatcher.call(name, arguments)
        return [
            TextContent(
                type="text",
                text=json.dumps(result, ensure_ascii=False),
            )
        ]

    return server
