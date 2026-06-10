"""MCP Server entry point for MAPCE.

Start with:
    python -m mapce.mcp.server

Configure in Claude Code settings.local.json:
    {
      "mcpServers": {
        "mapce": {
          "command": "uv",
          "args": ["run", "--directory", "/path/to/mapce", "python", "-m", "mapce.mcp.server"]
        }
      }
    }
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .tools import TOOL_DEFINITIONS, HANDLERS

logger = logging.getLogger("mapce.mcp")


@asynccontextmanager
async def mapce_lifespan(server: Server):
    """Startup: warm up embedding model. Shutdown: cleanup."""
    logger.info("MAPCE MCP Server starting up...")
    try:
        from mapce.core.embedding import embed_single
        _ = embed_single("startup warmup")
        logger.info("Embedding model loaded.")
    except Exception as e:
        logger.warning(f"Embedding model warm-up failed (will load on first use): {e}")
    try:
        yield
    finally:
        logger.info("MAPCE MCP Server shutting down.")


def create_server() -> Server:
    """Create and configure the MCP Server with all MAPCE tools."""
    server = Server("mapce", lifespan=mapce_lifespan)

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        return TOOL_DEFINITIONS

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name not in HANDLERS:
            raise ValueError(f"Unknown tool: {name}")
        handler = HANDLERS[name]
        try:
            result = await handler(**arguments)
        except Exception as e:
            logger.exception(f"Tool '{name}' failed")
            result = json.dumps({"status": "error", "message": str(e)})
        return [TextContent(type="text", text=result)]

    return server


def main():
    """Run the MCP server over stdio."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    server = create_server()

    async def run():
        async with stdio_server() as (reader, writer):
            await server.run(reader, writer, server.create_initialization_options())

    asyncio.run(run())


if __name__ == "__main__":
    main()
