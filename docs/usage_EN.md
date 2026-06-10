[中文](usage.md)<br>[← Back](../README_EN.md)

# Usage

MAPCE can be used via Python SDK or Claude Code natural language interaction. Both share the same set of MCP tools.

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
results, _ = search_code('self-attention implementation')

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
| `get_stats` | Index statistics (papers, code, chunks) | How big is my index? |

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

Replace `/path/to/mapce` with the actual path. Restart Claude Code, approve the server, and all tools above become available.

```bash
# Run standalone for debugging
uv run python -m mapce.mcp.server
```
