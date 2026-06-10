"""MCP tool implementations for MAPCE.

Each async handler calls into the core layer and returns JSON strings.
Tool definitions (Tool objects) are defined at module level for registration.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp.types import Tool

# Import handlers — they return JSON strings
from . import _handlers


# ---------------------------------------------------------------------------
# Tool definitions (MCP types)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    Tool(
        name="search_papers",
        description="Search indexed academic papers using 4-stage progressive retrieval. Returns results with titles, abstracts, methods, figures, and tables.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (natural language or keywords)"},
                "top_k": {"type": "integer", "description": "Max results (default: 10)", "default": 10},
                "year_min": {"type": "integer", "description": "Filter: minimum publication year"},
                "year_max": {"type": "integer", "description": "Filter: maximum publication year"},
                "venue": {"type": "string", "description": "Filter: publication venue (e.g., CoRL, ICRA, RSS)"},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="search_code",
        description="Search indexed code repositories. Returns code chunks with file paths, symbols, and call graphs.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query for code (function names, concepts, etc.)"},
                "top_k": {"type": "integer", "description": "Max results (default: 10)", "default": 10},
                "repo_name": {"type": "string", "description": "Optional: filter by repository name"},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="index_paper",
        description="Index a new paper into the knowledge base. Accepts local PDF path, arXiv ID, or URL.",
        inputSchema={
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "PDF file path, arXiv ID, or URL"},
                "source_type": {
                    "type": "string",
                    "description": "Type of source",
                    "enum": ["local", "arxiv", "url"],
                    "default": "local",
                },
                "language": {
                    "type": "string",
                    "description": "Paper language for OCR",
                    "enum": ["en", "ch"],
                    "default": "en",
                },
            },
            "required": ["source"],
        },
    ),
    Tool(
        name="index_code",
        description="Clone and index a code repository, linking it to an existing paper.",
        inputSchema={
            "type": "object",
            "properties": {
                "repo_url": {"type": "string", "description": "Git repository URL"},
                "paper_id": {"type": "string", "description": "Paper ID to associate the code with"},
            },
            "required": ["repo_url", "paper_id"],
        },
    ),
    Tool(
        name="list_indexed_papers",
        description="List all papers currently in the index with their status.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="get_paper_overview",
        description="Get a detailed overview of a paper: abstract, section list, figures, and tables.",
        inputSchema={
            "type": "object",
            "properties": {
                "paper_id": {"type": "string", "description": "Paper ID"},
            },
            "required": ["paper_id"],
        },
    ),
    Tool(
        name="delete_paper",
        description="Remove a paper and all its associated chunks from the index.",
        inputSchema={
            "type": "object",
            "properties": {
                "paper_id": {"type": "string", "description": "Paper ID to delete"},
            },
            "required": ["paper_id"],
        },
    ),
    Tool(
        name="get_stats",
        description="Get index statistics: total papers, chunks, papers with code.",
        inputSchema={"type": "object", "properties": {}},
    ),
]

# ---------------------------------------------------------------------------
# Handler mapping (name → async function returning JSON str)
# ---------------------------------------------------------------------------

HANDLERS = {
    "search_papers": _handlers.search_papers,
    "search_code": _handlers.search_code,
    "index_paper": _handlers.index_paper,
    "index_code": _handlers.index_code,
    "list_indexed_papers": _handlers.list_indexed_papers,
    "get_paper_overview": _handlers.get_paper_overview,
    "delete_paper": _handlers.delete_paper,
    "get_stats": _handlers.get_stats,
}
