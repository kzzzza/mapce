[中文](usage.md)<br>[← Back](../README_EN.md)

# Usage

MAPCE can be used via the Python SDK or Claude Code natural language interaction. MCP, the CLI, and the planned TUI share one local background service; the Python SDK remains available for development and maintenance scripts.

## Python SDK

```bash
cd mapce
uv run python
```

### Index a Paper

```python
# From arXiv
from mapce.core.indexing import index_paper_from_arxiv
paper_id = index_paper_from_arxiv('2511.04131')

# Local PDF
from mapce.core.indexing import index_paper
from pathlib import Path
paper_id = index_paper(Path.home() / 'Downloads' / 'paper.pdf')
```

### Index Code

After paper chunks are committed, MAPCE discovers GitHub repositories from the paper Markdown and arXiv comment. High-confidence repositories are indexed automatically, ambiguous links are recorded for review, and papers with no discovered link receive `no_code` without affecting paper retrieval. A repository supplied by the user is treated as high confidence.

```python
import asyncio
from mapce.mcp._handlers import index_code
result = asyncio.run(index_code(
    repo_url='https://github.com/LeCAR-Lab/BFM-Zero',
    paper_id='2511.04131'
))
```

### Search

```python
from mapce.core.retrieval import search_papers, search_code, search, SearchIntent

# Papers
results, intent = search_papers('transformer attention mechanism efficiency')
for r in results:
    print(f'[{r.year}] {r.title} — {r.section_path}')

# Code
results, _ = search_code(
    'self-attention implementation',
    paper_id='2511.04131',
    repo_url='https://github.com/LeCAR-Lab/BFM-Zero',
)

# Hybrid (papers + code)
intent = SearchIntent(intent='hybrid', sub_type='general')
results, _ = search('graph neural network message passing', intent=intent)
```

### View Index

```python
import asyncio
from mapce.mcp._handlers import get_stats, list_indexed_papers
print(asyncio.run(get_stats()))
print(asyncio.run(list_indexed_papers()))
```

The `vector_index` field returned by `get_stats` includes IVF_PQ/scalar indices, indexed and unindexed row counts, and effective query parameters. The same information is available from the read-only CLI:

```bash
.venv/bin/python scripts/manage_vector_index.py
```

## MCP Tool Reference

### search_papers

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | yes | Natural language or keywords |
| `top_k` | int | no | Max results (default 10) |
| `year_min` | int | no | Earliest publication year |
| `year_max` | int | no | Latest publication year |
| `venue` | string | no | Publication venue (e.g., CVPR, NeurIPS) |

> Search for image generation papers published at CVPR after 2024

### search_code

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | yes | Function name, class name, concept, etc. |
| `top_k` | int | no | Max results (default 10) |
| `repo_name` | string | no | Filter by repository name |
| `paper_id` | string | no | Restrict results to repositories linked to a paper |
| `repo_url` | string | no | Restrict results to a normalized GitHub repository URL |

> Find the FBModel implementation in BFM-Zero

### index_paper

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `source` | string | yes | PDF path, arXiv ID, or URL |
| `source_type` | string | no | `local` / `arxiv` / `url` (default `local`) |
| `language` | string | no | `en` or `ch` (default `en`) |

> Index this paper: https://arxiv.org/abs/2303.04137

### index_code

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `repo_url` | string | yes | Git repository URL |
| `paper_id` | string | yes | Paper ID to associate with |

> Index the code repository for paper 2511.04131

### get_paper_overview

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `paper_id` | string | yes | Paper ID |

> Show me the section structure and figure/table list for this paper

### Parameterless Tools

| Tool | Description | Natural Language Example |
|------|-------------|--------------------------|
| `list_indexed_papers` | List all indexed papers with status | What papers are in my index? |
| `delete_paper` | Delete a paper by `paper_id` | Remove paper 2303.04137 |
| `get_stats` | Index statistics (papers, code, chunks, vector coverage) | How big is my index? |

## MCP Server (Claude Code Integration)

Create `.mcp.json` in the project root:

```json
{
  "mcpServers": {
    "mapce": {
      "command": "/opt/homebrew/bin/uv",
      "args": [
        "run",
        "--directory", "/path/to/mapce",
        "--env-file", "/path/to/mapce/.env",
        "python", "-m", "mapce.mcp.server"
      ]
    }
  }
}
```

Replace `/path/to/mapce` with the actual path. Restart Claude Code, approve the server, and all tools above become available. The stdio entry point only forwards requests and does not load LanceDB or the embedding model; clients using the same `MAPCE_DATA_DIR` reuse one service.

```bash
# Service management
uv run mapce serve
uv run mapce serve-status
uv run mapce serve-logs
uv run mapce serve-kill

# Debug the stdio proxy
uv run python -m mapce.mcp.server
```
