<p align="center">
  <img src="img/logo.png" alt="MAPCE logo" width="100%">
</p>

[中文](README.md)

MAPCE is a personal RAG knowledge base for general CS academic research. It supports PDF parsing, structured code repository chunking, and vector + full-text hybrid retrieval, served as an MCP Server to provide reusable academic knowledge retrieval for AI agents.

> [bolg about this project](https://kzzzza.github.io/2026/06/09/Tool_agent_paper_research/)

### Use Cases

- Literature survey & systematic review — cross-paper semantic search with year/venue filtering
- Algorithm implementation reference — bidirectional search between paper methods and source code with call-graph tracking
- Reproduction assistance — targeted retrieval of tables (benchmark data), figures (architecture diagrams), and training configs
- Academic writing — quickly locate specific sections, methods, and experimental conclusions in related work

## Installation

- Python ≥ 3.11 · [uv](https://astral.sh/uv) package manager · [MinerU API Token](https://mineru.net/apiManage/token) (free registration)
- macOS / Linux (Apple Silicon recommended) · 16 GB RAM · ~5 GB disk

```bash
# 1. Install uv (if not installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Enter project and sync dependencies
cd mapce
uv sync

# 3. Configure environment variables
cp .env.example .env
# Edit .env — at minimum, fill in MINERU_API_TOKEN
# Users in mainland China: uncomment proxy lines and fill in your proxy address

# 4. Initialize database and download embedding model (first run only, ~2 GB)
uv run --env-file .env python scripts/init_db.py
```

### .env Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MINERU_API_TOKEN` | — | **Required**. MinerU API key |
| `MAPCE_DATA_DIR` | `~/.mapce/data` | LanceDB data directory |
| `MAPCE_EMBEDDING_MODEL` | `intfloat/multilingual-e5-large` | Embedding model (fastembed) |
| `MAPCE_LOG_LEVEL` | `INFO` | Log level |
| `http_proxy` / `https_proxy` | — | HTTP proxy (required for mainland China) |

### Proxy Configuration (mainland China users)

Edit `.env` and uncomment:

```bash
http_proxy=http://127.0.0.1:9674
https_proxy=http://127.0.0.1:9674
```

`uv run --env-file .env` and the MCP Server's `--env-file` flag load these automatically. No manual `export` needed.

### Choosing an Embedding Model

```bash
# List available models
uv run python -c "from fastembed import TextEmbedding; print([m['model'] for m in TextEmbedding.list_supported_models()])"
```

## Claude Code Integration

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

Replace `/path/to/mapce` with the actual path. Restart Claude Code, approve the MAPCE server, and interact in natural language:

> Search for papers on diffusion policy for robot control
>
> Does this paper have open-source code? Index it for me
>
> Find papers and code about attention mechanisms in transformer architectures

## Python SDK Quickstart

```python
# Index a paper
from mapce.core.indexing import index_paper_from_arxiv
paper_id = index_paper_from_arxiv('2511.04131')

# Index code
import asyncio
from mapce.mcp._handlers import index_code
result = asyncio.run(index_code(repo_url='https://github.com/...', paper_id='2511.04131'))

# Search
from mapce.core.retrieval import search_papers, search_code
results, _ = search_papers('diffusion policy visuomotor control')
results, _ = search_code('self-attention transformer implementation')
```

## Doc Index

| Doc | Content |
|-----|---------|
| [docs/usage.md](docs/usage.md) | Python SDK usage, MCP tool reference (8 tools), Claude Code integration |
| [docs/data-sources.md](docs/data-sources.md) | Data source adapters (arXiv, Zotero, local PDF, batch directory) |
| [docs/storage.md](docs/storage.md) | Storage: LanceDB, model cache, temp files, cleanup |
| [docs/troubleshooting.md](docs/troubleshooting.md) | FAQ and solutions |
| [docs/development.md](docs/development.md) | Development guide (architecture, chunking strategy, project structure) |

## MAPCE TODO

- [ ] **Code Analysis Enhancement**: Python AST parsing works decently, but C++/CUDA relies on regex hacks — template metaprogramming and complex macro expansion are basically unhandled. Need to support more languages (Makefile, Dockerfile, shell scripts, etc.)
- [ ] **Retrieval Quality Optimization**: Chunking strategy heavily impacts retrieval — too coarse and results are imprecise, too fine and context is insufficient. Needs further iteration and testing.
- [ ] **Auto-Update Mechanism**: Automatically detect new arXiv versions and new commits in code repos. Ideal setup: run on a personal server with a loop, detect changes, and notify the user via WeChat / Feishu to confirm syncing.
- [ ] **Frontend UI**: Currently CLI + MCP only — convenient for agents but unfriendly for humans. Need a simple frontend for browsing indexed content.
- [ ] **Retrieval Benchmarking**: Right now it just "works." Needs systematic evaluation — agent retrieval quality, token savings, recall rate, and other metrics.
- [ ] **Deep Zotero Integration**: Go beyond just extracting PDFs — sync Zotero user notes into the database, or build a Zotero-integrated agent plugin.

