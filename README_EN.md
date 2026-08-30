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
- macOS / Linux (Apple Silicon recommended) · 16 GB RAM · ~3 GB disk

```bash
# 1. Install uv (if not installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Enter project and sync dependencies
git clone https://github.com/kzzzza/mapce.git
cd mapce
uv sync

# 3. Configure environment variables
cp .env.example .env
# Edit .env — at minimum, fill in MINERU_API_TOKEN
# Users in mainland China: uncomment proxy lines and fill in your proxy address

# 4. Initialize database and download embedding model (first run only, ~2.1 GB)
uv run --env-file .env python scripts/init_db.py
```

### .env Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MINERU_API_TOKEN` | — | **Required**. MinerU API key |
| `MAPCE_DATA_DIR` | `~/.mapce/data` | LanceDB data directory |
| `MAPCE_EMBEDDING_MODEL` | `intfloat/multilingual-e5-large` | Embedding model (fastembed) |
| `MAPCE_EMBEDDING_CACHE_DIR` | `$MAPCE_DATA_DIR/models/fastembed` | Persistent embedding model cache |
| `MAPCE_SERVICE_PORT` | `8765` | Local singleton service port, bound only to `127.0.0.1` |
| `MAPCE_WARMUP_EMBEDDING` | `0` | Load the embedding model at startup; disabled for lazy loading by default |
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

MAPCE now keeps its LanceDB connection and embedding model in one local background service. One service is allowed per `MAPCE_DATA_DIR`; the stdio process started by Claude Code is a lightweight proxy that starts or reuses that service. Existing MCP configuration remains valid.

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

### Background Service Management

```bash
uv run --env-file .env mapce serve
uv run --env-file .env mapce serve-status
uv run --env-file .env mapce serve-logs
uv run --env-file .env mapce serve-kill
uv run --env-file .env mapce serve-restart
```

Closing an MCP client leaves the background service running. `serve-kill` requests a graceful shutdown; `serve-kill --force` only targets the exact process whose identity passed the service health check.

## Terminal Database Manager

Run `mapce` without a subcommand to open the Textual TUI. It accesses the database only through the same local service, so the UI process does not load LanceDB or the embedding model.

```bash
uv run --env-file .env mapce
```

The five tabs cover dashboard, paper inventory, indexing, jobs, and system diagnostics. The paper inventory uses one scrollable table without pagination. You can resolve a paper by internal ID or arXiv ID, inspect paper/code state, submit indexing and deletion jobs, review repository candidates, and inspect logs. Pressing `q` closes only the UI client and leaves the service running.

For scripted management, use `mapce papers`, `mapce search`, `mapce index`, `mapce jobs`, `mapce stats`, and `mapce doctor`; run each command with `--help` for its options.

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
| [docs/usage.md](docs/usage.md) | TUI/CLI, Python SDK, MCP tool reference (11 tools), deep paper reading, and Agent integration |
| [docs/data-sources.md](docs/data-sources.md) | Data source adapters (arXiv, Zotero, local PDF, batch directory) |
| [docs/storage.md](docs/storage.md) | Storage: LanceDB, model cache, temp files, cleanup |
| [docs/troubleshooting.md](docs/troubleshooting.md) | FAQ and solutions |
| [docs/development.md](docs/development.md) | Development guide (architecture, chunking strategy, project structure) |

## MAPCE TODO

- [x] **Paper Retrieval Breadth and Memory Safety**: Added hybrid dense/full-text retrieval, paper-level deduplication, and best-evidence selection. IVF-PQ indexing, connection reuse, and opt-in embedding warmup reduce memory use from repeated searches and duplicate MCP processes.
- [x] **Paper-to-Code Repository Associations**: Separated paper and code states, added multi-repository associations, official repository discovery, reviewable candidates, and an explicit state for papers where no repository was found.
- [ ] **Code Retrieval Ranking**: The current code-file `Recall@5` baseline is approximately 0.65. Improve ranking with repository, file-path, symbol, and call-graph signals, backed by finer-grained evaluation sets for different languages.
- [ ] **Code Analysis Enhancement**: Python uses AST parsing, while C++/CUDA still relies on regular expressions and cannot reliably handle template metaprogramming or complex macro expansion. Consider Tree-sitter or language-server integration, plus Makefile, Dockerfile, and shell support.
- [ ] **Auto-Update Mechanism**: Detect new arXiv versions and repository commits, present changes for user confirmation, then apply incremental updates. Also refresh auxiliary indexes and retry failed jobs.
- [x] **Terminal Management UI**: Added a lightweight Textual TUI for paper-state browsing, exact arXiv lookup, indexing jobs, repository review, confirmed deletion, logs, and diagnostics. TUI, CLI, and MCP reuse one singleton service.
- [ ] **Deep Zotero Integration**: Go beyond PDF import by syncing Zotero notes, tags, and collections, or provide a Zotero Agent plugin.

## License

[MIT](LICENSE)
