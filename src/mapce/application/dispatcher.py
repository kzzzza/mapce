"""Dispatch MCP-compatible tools while serializing database writes."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any


WRITE_TOOLS = frozenset({
    "index_paper",
    "index_code",
    "delete_paper",
    "review_code_repository",
    "delete_code_repository",
})
SEMANTIC_TOOLS = frozenset({"search_papers", "search_code"})
logger = logging.getLogger("mapce.application.dispatcher")


class ToolDispatcher:
    """Run existing handlers behind one shared write lock."""

    def __init__(self) -> None:
        self._write_lock = asyncio.Lock()
        self._semantic_limit = asyncio.Semaphore(1)

    @staticmethod
    async def _invoke(handler: Any, arguments: dict[str, Any]) -> str:
        """Keep blocking database, model, and network work off the ASGI loop."""
        return await asyncio.to_thread(lambda: asyncio.run(handler(**arguments)))

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        from mapce.mcp.tools import HANDLERS

        handler = HANDLERS.get(name)
        if handler is None:
            return {
                "status": "error",
                "error_code": "unknown_tool",
                "message": f"Unknown tool: {name}",
            }

        try:
            if name in WRITE_TOOLS:
                async with self._write_lock:
                    raw = await self._invoke(handler, arguments)
            elif name in SEMANTIC_TOOLS:
                async with self._semantic_limit:
                    raw = await self._invoke(handler, arguments)
            else:
                raw = await self._invoke(handler, arguments)
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("Tool returned a non-object JSON value")
            return value
        except TypeError as exc:
            return {
                "status": "error",
                "error_code": "invalid_arguments",
                "message": str(exc),
            }
        except Exception as exc:
            logger.exception("Tool execution failed: %s", name)
            return {
                "status": "error",
                "error_code": "tool_execution_failed",
                "message": str(exc),
            }
