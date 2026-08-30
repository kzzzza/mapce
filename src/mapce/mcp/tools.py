"""MCP tool implementations for MAPCE.

Each async handler calls into the core layer and returns JSON strings.
Tool definitions (Tool objects) are defined at module level for registration.
"""

from __future__ import annotations

from mcp.types import Tool

# Import handlers — they return JSON strings
from . import _handlers


STATUS_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string"},
        "error_code": {"type": "string"},
        "message": {"type": ["string", "null"]},
    },
    "required": ["status"],
    "additionalProperties": True,
}

RESOLVE_PAPER_OUTPUT_SCHEMA = {
    **STATUS_OUTPUT_SCHEMA,
    "properties": {
        **STATUS_OUTPUT_SCHEMA["properties"],
        "input": {"type": "string"},
        "paper_id": {"type": "string"},
        "arxiv_id": {"type": ["string", "null"]},
        "title": {"type": "string"},
        "authors": {"type": "array", "items": {"type": "string"}},
        "paper_status": {"type": "string"},
        "code_status": {"type": "string"},
        "indexed_at": {"type": ["string", "null"]},
    },
}

READ_SECTION_OUTPUT_SCHEMA = {
    **STATUS_OUTPUT_SCHEMA,
    "properties": {
        **STATUS_OUTPUT_SCHEMA["properties"],
        "paper_id": {"type": "string"},
        "section_path": {"type": ["string", "null"]},
        "count": {"type": "integer"},
        "total_chunks": {"type": "integer"},
        "next_cursor": {"type": ["string", "null"]},
        "chunks": {"type": "array", "items": {"type": "object"}},
    },
}

SEARCH_CONTENT_OUTPUT_SCHEMA = {
    **STATUS_OUTPUT_SCHEMA,
    "properties": {
        **STATUS_OUTPUT_SCHEMA["properties"],
        "paper_id": {"type": "string"},
        "query": {"type": "string"},
        "count": {"type": "integer"},
        "results": {"type": "array", "items": {"type": "object"}},
    },
}


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
                "top_k": {"type": "integer", "description": "Max distinct papers (default: 10)", "default": 10},
                "year_min": {"type": "integer", "description": "Filter: minimum publication year"},
                "year_max": {"type": "integer", "description": "Filter: maximum publication year"},
                "venue": {"type": "string", "description": "Filter: publication venue (e.g., CoRL, ICRA, RSS)"},
            },
            "required": ["query"],
        },
        outputSchema=STATUS_OUTPUT_SCHEMA,
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
                "paper_id": {"type": "string", "description": "Optional: restrict search to one paper's repositories"},
                "repo_url": {"type": "string", "description": "Optional: restrict search to one normalized GitHub repository URL"},
            },
            "required": ["query"],
        },
        outputSchema=STATUS_OUTPUT_SCHEMA,
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
        outputSchema=STATUS_OUTPUT_SCHEMA,
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
        outputSchema=STATUS_OUTPUT_SCHEMA,
    ),
    Tool(
        name="list_indexed_papers",
        description="List all papers currently in the index with their status.",
        inputSchema={"type": "object", "properties": {}},
        outputSchema=STATUS_OUTPUT_SCHEMA,
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
        outputSchema=STATUS_OUTPUT_SCHEMA,
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
        outputSchema=STATUS_OUTPUT_SCHEMA,
    ),
    Tool(
        name="get_stats",
        description="Get index statistics: total papers, chunks, papers with code.",
        inputSchema={"type": "object", "properties": {}},
        outputSchema=STATUS_OUTPUT_SCHEMA,
    ),
    Tool(
        name="resolve_paper",
        description=(
            "Resolve an indexed paper from an internal ID, arXiv ID, arXiv: prefix, "
            "versioned ID, or arXiv URL. This performs no network request."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "identifier": {
                    "type": "string",
                    "description": "Internal paper ID or arXiv reference",
                },
            },
            "required": ["identifier"],
        },
        outputSchema=RESOLVE_PAPER_OUTPUT_SCHEMA,
    ),
    Tool(
        name="read_paper_section",
        description=(
            "Read paginated paper content by exact section path or chunk ID. "
            "Returns source locations and text without embedding vectors."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "paper_id": {"type": "string"},
                "section_path": {"type": "string"},
                "chunk_id": {"type": "string"},
                "include_subsections": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10},
                "cursor": {"type": "string"},
            },
            "required": ["paper_id"],
            "oneOf": [
                {"required": ["section_path"], "not": {"required": ["chunk_id"]}},
                {"required": ["chunk_id"], "not": {"required": ["section_path"]}},
            ],
        },
        outputSchema=READ_SECTION_OUTPUT_SCHEMA,
    ),
    Tool(
        name="search_paper_content",
        description=(
            "Search for multiple relevant chunks inside one indexed paper. "
            "Unlike search_papers, results are not deduplicated at paper level."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "paper_id": {"type": "string"},
                "query": {"type": "string"},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10},
            },
            "required": ["paper_id", "query"],
        },
        outputSchema=SEARCH_CONTENT_OUTPUT_SCHEMA,
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
    "resolve_paper": _handlers.resolve_paper,
    "read_paper_section": _handlers.read_paper_section,
    "search_paper_content": _handlers.search_paper_content,
}
