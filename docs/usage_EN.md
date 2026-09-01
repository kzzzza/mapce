[中文](usage.md)<br>[← Back](../README_EN.md)

# Usage

MAPCE provides a TUI database manager, a scriptable CLI, MCP tools for Agents, and a Python SDK. TUI, CLI, and MCP share one local background service; the Python SDK remains available for development and maintenance scripts.

## TUI Database Manager

```bash
mapce
```

The TUI is a database-management and status-visualization interface. Paper understanding and note writing remain the responsibility of an Agent calling MAPCE over MCP.

| Tab | Functions |
|-----|-----------|
| Dashboard | Service memory, paper/chunk counts, database size, code states, and auxiliary indexes |
| Papers | Inventory and filters, exact internal/arXiv lookup, semantic search, abstract/outline/repository details, and confirmed deletion |
| Index | Submit paper/code jobs, approve, ignore, or select repository candidates, and delete one repository index |
| Jobs | Inspect serialized writes, cancel queued jobs, and retry failed jobs |
| System | Paths, memory and index diagnostics, recent logs, reconnect, and confirmed service restart |

The interface requires a terminal of at least 76×22. Pressing `q` closes only the TUI; use `mapce serve-kill` when the service itself should stop.

## CLI Management Commands

After the first global installation, save the default environment file so commands work from any directory:

```bash
uv tool install /path/to/mapce
mapce config set-env /path/to/mapce/.env
mapce config show
```

```bash
mapce papers list
mapce papers find 2412.04368 --json
mapce papers show 2412.04368
mapce search paper "diffusion policy" --top-k 10
mapce search content 2412.04368 "training objective"
mapce index paper 2501.00001 --type arxiv
mapce index code https://github.com/owner/repo --paper 2501.00001
mapce jobs list
mapce stats
mapce doctor
```

Indexing and deletion run through the serialized background queue. Commands with `--json` are suitable for scripts; run `mapce <command> --help` for complete options.

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

Every tool declares an `outputSchema`. New MCP clients receive `structuredContent`, while a JSON `TextContent` fallback remains available for older clients. Failed calls set `isError=true` and include a stable `error_code`.

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

The overview also returns a `citation` field identical to `get_paper_citation`. The TUI paper detail view displays its plain-text citation, BibTeX, CSL-JSON, DOI, URL, missing fields, and verification status.

### get_paper_citation

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `paper_id` | string | yes | Unified ID of an indexed paper |

Returns the title, authors, year, venue, DOI, and arXiv ID already stored in the local index, plus a stable citation key, plain-text citation, BibTeX, and CSL-JSON. It makes no network request. `verification_status=stored_metadata_only` means that an author should still verify the citation against the original paper or an authoritative metadata source.

> Export BibTeX and CSL-JSON for paper 2412.04368

### resolve_paper

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `identifier` | string | yes | Internal paper ID, arXiv ID, versioned ID, `arXiv:` prefix, or arXiv URL |

This tool only queries local `index_meta`. It does not access the network or load the embedding model. Versions are removed, and legacy IDs such as `hep-th/9901001` are supported.

### read_paper_section

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `paper_id` | string | yes | Canonical paper ID returned by `resolve_paper` |
| `section_path` | string | one of two | Exact section path |
| `chunk_id` | string | one of two | Chunk ID from an overview or search result |
| `include_subsections` | bool | no | Include descendant sections; default `false` |
| `limit` | int | no | 1–20 chunks per page; default 10 |
| `cursor` | string | no | Cursor returned by the previous page |

Section reading prefers L3 paragraphs, avoiding duplicate L2 blocks containing the same text. Results include section, level, order, neighboring chunk IDs, and content, but no embedding vector.

### search_paper_content

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `paper_id` | string | yes | One paper to search |
| `query` | string | yes | Question or keywords within the paper |
| `top_k` | int | no | Return 1–20 relevant chunks; default 10 |

This tool searches only the specified paper and can return multiple content chunks. Its semantics are separate from `search_papers`, which returns each paper at most once.

### Agent Deep-Reading Flow

```text
resolve_paper
  → get_paper_overview
  → get_paper_citation
  → read_paper_section / search_paper_content
  → search_code (when indexed code exists)
  → Agent organizes an explanation or paper notes
```

MAPCE returns content with source locations; the calling Agent remains responsible for writing notes.

### Parameterless Tools

| Tool | Description | Natural Language Example |
|------|-------------|--------------------------|
| `list_indexed_papers` | List all indexed papers with status | What papers are in my index? |
| `delete_paper` | Delete a paper by `paper_id` | Remove paper 2303.04137 |
| `get_stats` | Index statistics (papers, code, chunks, vector coverage) | How big is my index? |

## MCP Server (Claude Code Integration)

The global installation also provides the lightweight `mapce-mcp` stdio command. Create `.mcp.json` in the project root and replace the command path with the output of `command -v mapce-mcp`:

```json
{
  "mcpServers": {
    "mapce": {
      "command": "/path/to/mapce-mcp",
      "args": []
    }
  }
}
```

Restart Claude Code, approve the server, and all tools above become available. The stdio entry point only forwards requests and does not load LanceDB or the embedding model; clients using the same `MAPCE_DATA_DIR` reuse one service.

```bash
# Service management
mapce serve
mapce serve-status
mapce serve-logs
mapce serve-kill

# Debug the stdio proxy
mapce-mcp
```
