[中文](development.md)<br>[← Back](../README_EN.md)

# Development

## Environment

```bash
uv sync        # includes dev dependencies
uv run pytest  # run tests
```

## Dependency Management

```bash
uv add <package>        # add runtime dependency
uv add --dev <package>   # add dev dependency
```

## Architecture Overview

### Project Structure

```
mapce/
├── pyproject.toml
├── .env.example
├── README.md
├── img/                         # Logo and static assets
├── scripts/init_db.py
├── docs/
│
├── src/mapce/
│   ├── core/                    # Core engine (no MCP dependency)
│   │   ├── embedding.py         # fastembed wrapper
│   │   ├── indexing.py          # Indexing orchestrator
│   │   ├── retrieval.py         # 4-stage retrieval
│   │   ├── incremental.py       # Incremental indexing (dedup, state machine, deletion)
│   │   ├── code_mapper.py       # Paper↔Code mapping
│   │   └── chunking/
│   │       ├── paper.py         # Paper chunker
│   │       └── code.py          # Code chunker (AST parsing)
│   │
│   ├── db/                      # Data access layer
│   │   ├── connection.py        # LanceDB connection
│   │   ├── schema.py            # PyArrow schemas
│   │   └── operations.py        # CRUD
│   │
│   ├── contracts/               # HTTP, job, and error response models
│   ├── application/             # Tool dispatch and serialized write jobs
│   ├── service/                 # Singleton lock, HTTP service, process lifecycle
│   ├── client/                  # Shared HTTP client for CLI, TUI, and stdio proxy
│   ├── cli.py                   # Service management entry point
│   │
│   ├── mineru/                  # MinerU API wrapper
│   │   ├── api.py               # httpx implementation
│   │   └── parser.py            # Output parser
│   │
│   ├── mcp/                     # MCP transport adapters
│   │   ├── server.py            # Lightweight stdio HTTP proxy
│   │   ├── backend.py           # Streamable HTTP MCP inside the service
│   │   ├── tools.py             # Tool definitions
│   │   └── _handlers.py         # Async handlers
│   │
│   ├── prompts/                 # Jinja2 templates
│   └── sources/                 # Data source adapters
│       ├── arxiv.py
│       ├── zotero.py
│       └── local.py
│
└── tests/
```

In production, one background service owns each normalized `MAPCE_DATA_DIR`. A lifetime `flock` prevents duplicate instances, while the service centralizes LanceDB, the lazily loaded embedding model, and serialized write jobs. The CLI and stdio MCP proxy use the local HTTP client and do not load the database or model when imported.

### Indexing Pipeline

```
PDF/arXiv → MinerU parsing → chunking → embedding → LanceDB
                                  ↓
                          figures + tables (image paths, table HTML in persistent cache)
```

**Paper Chunking (3 layers + 2 special)**

| Layer | Content | Size | Purpose |
|-------|---------|------|---------|
| L1 | Title + abstract + keywords | ~200–500 tokens | Coarse screening |
| L2 | Section-level (MinerU section boundaries) | ~500–2000 tokens | Fine ranking |
| L3 | Paragraph-level | ~200–500 tokens | Prompt injection |
| Figure | Figure caption + image path | — | Indirect image retrieval |
| Table | Table caption + HTML content + table image | — | Benchmark retrieval |

**Code Chunking (5 layers + Config)**

| Layer | Content | Purpose |
|-------|---------|---------|
| L1 | README summary + directory tree + entry points + build info | Repository overview |
| L2 | File-level: path + imports + signatures + exports | File location |
| L3 | Function/class: full implementation + calls[] + called_by[] | Prompt injection |
| L4 | Module-level: top-level constants, registries, decorators, `__main__` | Context completion |
| L5 | Test functions (linked to tested symbols) | Expected behavior |
| Config | YAML/JSON/TOML hyperparameters | Hyperparameter retrieval |

### Retrieval Pipeline

```
Stage 0: Query understanding → intent extraction (paper / code / hybrid)
Stage 1: Paper coarse screening → L1 vector search top-20 + metadata filtering
Stage 2: Section/code fine ranking → L2 vector search, papers and code in parallel
Stage 3: Context expansion → L3 paragraphs + neighbor chains + figure/table lateral + call graph
Stage 4: Result assembly → structured prompt injection with token budget control
```

`chunks.embedding` uses IVF_PQ (24 partitions, 128 PQ sub-vectors) for candidate generation. Queries probe 16 partitions and use `refine_factor=8` to rerank with original vectors. Scalar indices on `chunk_type`, `paper_id`, `repo_name`, `repo_url`, `year`, and `venue` accelerate prefilters. Result projections explicitly exclude the 1024-float embedding column.

### Database

Four LanceDB tables are used: `chunks` stores paper and code chunks, `paper_code_repos` stores paper-to-repository associations, `paper_code_mapping` optionally stores method-to-symbol links, and `index_meta` stores indexing metadata.

### Incremental Indexing

- **Dedup**: arxiv_id exact → doi exact → title vector similarity > 0.95
- **State machine**: papers use pending → chunking → complete | failed; code progress uses the independent `code_status`
- **Deletion**: cascading check — shared code chunks preserved, exclusive ones removed
- **Vector maintenance**: each successful chunk batch creates or refreshes IVF_PQ/scalar indices as needed; maintenance failure never rolls back valid paper data, and LanceDB still searches uncovered rows through its compatibility path

## Adding a Data Source

1. Create a new file under `sources/` implementing search/download/import logic
2. All indexing flows through `core/indexing.py`'s `index_paper` or `_index_from_mineru_dir`
3. Persistent cache is managed automatically: MinerU output goes to `~/.mapce/data/papers/`, redundant files auto-cleaned (only `.md`, `_content_list_v2.json`, `images/` retained)

## Switching Embedding Models

Change `MAPCE_EMBEDDING_MODEL` in `.env`, then reinitialize or call `re_embed_all()`:

```python
from mapce.core.incremental import re_embed_all
re_embed_all()
```
