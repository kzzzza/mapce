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
│   ├── mineru/                  # MinerU API wrapper
│   │   ├── api.py               # httpx implementation
│   │   └── parser.py            # Output parser
│   │
│   ├── mcp/                     # MCP Server layer
│   │   ├── server.py            # stdio entry point
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

### Database

Three LanceDB tables: `chunks` (main), `paper_code_mapping` (Paper↔Code links), `index_meta` (index metadata). Linked via chunk_id string references.

### Incremental Indexing

- **Dedup**: arxiv_id exact → doi exact → title vector similarity > 0.95
- **State machine**: pending → chunking → complete | code_pending | failed
- **Deletion**: cascading check — shared code chunks preserved, exclusive ones removed

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
