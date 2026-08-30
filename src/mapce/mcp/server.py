"""Backward-compatible stdio MCP proxy for the singleton MAPCE service."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, Tool

from mapce.client import MapceClient, ServiceClientError

from .tools import TOOL_DEFINITIONS
from .protocol import to_mcp_result

logger = logging.getLogger("mapce.mcp.proxy")


def create_server() -> Server:
    """Create the lightweight stdio proxy without importing database modules."""
    client = MapceClient(auto_start=True)

    @asynccontextmanager
    async def proxy_lifespan(_: Server):
        client.connect()
        try:
            yield {"client": client}
        finally:
            client.close()

    server = Server("mapce", lifespan=proxy_lifespan)

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        return TOOL_DEFINITIONS

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict) -> CallToolResult:
        try:
            result = await client.call_tool_async(name, arguments)
        except ServiceClientError as exc:
            result = {
                "status": "error",
                "error_code": exc.error_code,
                "message": str(exc),
            }
        return to_mcp_result(result)

    return server


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    from mapce.configuration import ConfigurationError, load_configured_env

    try:
        load_configured_env(strict=True)
    except ConfigurationError as exc:
        logger.error("%s: %s", exc.error_code, exc)
        raise SystemExit(78) from exc
    server = create_server()

    async def run() -> None:
        async with stdio_server() as (reader, writer):
            await server.run(reader, writer, server.create_initialization_options())

    asyncio.run(run())


if __name__ == "__main__":
    main()
