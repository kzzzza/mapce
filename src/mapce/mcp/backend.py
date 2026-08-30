"""MCP server implementation owned by the singleton MAPCE service."""

from __future__ import annotations

from mcp.server import Server
from mcp.types import CallToolResult, Tool

from mapce.application import ToolDispatcher

from .tools import TOOL_DEFINITIONS
from .protocol import to_mcp_result


def create_backend_mcp_server(dispatcher: ToolDispatcher) -> Server:
    server = Server("mapce")

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        return TOOL_DEFINITIONS

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict) -> CallToolResult:
        result = await dispatcher.call(name, arguments)
        return to_mcp_result(result)

    return server
