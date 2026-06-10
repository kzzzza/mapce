[中文](data-sources.md)<br>[← Back](../README_EN.md)

# Data Sources

All imports go through the `index_paper` tool or its corresponding Python API.

## arXiv

```python
from mapce.core.indexing import index_paper_from_arxiv
paper_id = index_paper_from_arxiv('2511.04131')
```

Uses MinerU's URL-based extraction to auto-download and index.

### Batch Search & Index

```python
from mapce.sources.arxiv import search_and_index_arxiv
results = search_and_index_arxiv("diffusion models image generation", max_results=10)
```

## Local PDF

```python
from mapce.core.indexing import index_paper
from pathlib import Path
paper_id = index_paper(Path.home() / 'Downloads' / 'paper.pdf')
```

Uses MinerU's batch upload API for parsing.

### Directory Batch Import

```python
from mapce.sources.local import index_directory
results = index_directory(Path.home() / "Papers" / "cvpr2024")
```

Recursively scans a directory for all PDFs and indexes them, with automatic deduplication.

## URL

```python
# MCP tool: set source_type="url"
# Python SDK: index_paper_from_arxiv covers most URL scenarios
```

## Zotero

Reads directly from the local Zotero SQLite database:

```python
from mapce.sources.zotero import import_from_zotero

# Import from a specific collection
results = import_from_zotero(collection_name="Reinforcement_Learning", max_items=50)

# Import all journal articles
results = import_from_zotero(item_type="journalArticle", max_items=100)
```

Auto-extracts title, authors, DOI, and arXiv ID. Prefers locally stored PDF attachments when available.
