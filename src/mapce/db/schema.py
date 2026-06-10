"""LanceDB table schemas.

Three tables:
  - chunks: unified storage for all chunk types (paper, code, special)
  - paper_code_mapping: Paper <-> Code bidirectional links
  - index_meta: indexing metadata for incremental update support
"""

import pyarrow as pa

# ---------------------------------------------------------------------------
# chunks — main table
# ---------------------------------------------------------------------------

CHUNKS_SCHEMA = pa.schema([
    # --- base fields (all chunk types) ---
    pa.field("chunk_id", pa.string(), nullable=False),
    pa.field("chunk_type", pa.string(), nullable=False),
    # paper_l1 | paper_l2 | paper_l3 | figure | table
    # | code_l1 | code_l2 | code_l3 | code_l4 | code_l5 | code_config
    pa.field("source_type", pa.string(), nullable=False),  # "paper" | "code"
    pa.field("paper_id", pa.string(), nullable=True),       # FK to index_meta
    pa.field("content", pa.string(), nullable=False),       # embed + inject text
    pa.field("embedding", pa.list_(pa.float32(), list_size=1024), nullable=True),
    pa.field("fulltext_search", pa.string(), nullable=True), # LanceDB FTS column

    # --- paper-specific fields ---
    pa.field("title", pa.string(), nullable=True),
    pa.field("authors", pa.list_(pa.string()), nullable=True),
    pa.field("year", pa.int32(), nullable=True),
    pa.field("venue", pa.string(), nullable=True),
    pa.field("arxiv_id", pa.string(), nullable=True),
    pa.field("doi", pa.string(), nullable=True),
    pa.field("section_path", pa.string(), nullable=True),   # e.g. "2. Method > 2.3 Loss"
    pa.field("section_level", pa.int32(), nullable=True),   # 1 2 3 99(special)
    pa.field("chunk_index", pa.int32(), nullable=True),
    pa.field("prev_chunk_id", pa.string(), nullable=True),
    pa.field("next_chunk_id", pa.string(), nullable=True),

    # --- code-specific fields ---
    pa.field("repo_name", pa.string(), nullable=True),
    pa.field("repo_url", pa.string(), nullable=True),
    pa.field("file_path", pa.string(), nullable=True),
    pa.field("line_range", pa.list_(pa.int32(), list_size=2), nullable=True),
    pa.field("language", pa.string(), nullable=True),
    pa.field("symbol_name", pa.string(), nullable=True),
    pa.field("symbol_type", pa.string(), nullable=True),
    # function | class | method | module | global_var | test
    pa.field("signature", pa.string(), nullable=True),
    pa.field("docstring", pa.string(), nullable=True),
    pa.field("calls", pa.list_(pa.string()), nullable=True),      # chunk_ids called
    pa.field("called_by", pa.list_(pa.string()), nullable=True),  # chunk_ids calling this
    pa.field("type_refs", pa.list_(pa.string()), nullable=True),  # custom type locations
    pa.field("imports", pa.list_(pa.string()), nullable=True),
    pa.field("associated_test", pa.string(), nullable=True),

    # --- special chunk fields ---
    pa.field("figure_path", pa.string(), nullable=True),
    pa.field("figure_index", pa.int32(), nullable=True),
    pa.field("table_markdown", pa.string(), nullable=True),
    pa.field("table_image", pa.string(), nullable=True),
    pa.field("table_dims", pa.string(), nullable=True),
    pa.field("config_keys", pa.list_(pa.string()), nullable=True),
])

# ---------------------------------------------------------------------------
# paper_code_mapping — Paper <-> Code links
# ---------------------------------------------------------------------------

MAPPING_SCHEMA = pa.schema([
    pa.field("mapping_id", pa.string(), nullable=False),
    pa.field("paper_id", pa.string(), nullable=False),
    pa.field("paper_method", pa.string(), nullable=False),
    pa.field("code_chunk_id", pa.string(), nullable=False),
    pa.field("repo_name", pa.string(), nullable=False),
    pa.field("confidence", pa.string(), nullable=False),   # high | medium | low
    pa.field("evidence", pa.string(), nullable=True),
    pa.field("created_by", pa.string(), nullable=False),   # subagent | manual | heuristic
    pa.field("verified", pa.bool_(), nullable=False),
])

# ---------------------------------------------------------------------------
# index_meta — indexing metadata
# ---------------------------------------------------------------------------

INDEX_META_SCHEMA = pa.schema([
    pa.field("paper_id", pa.string(), nullable=False),
    pa.field("title", pa.string(), nullable=False),
    pa.field("arxiv_id", pa.string(), nullable=True),
    pa.field("doi", pa.string(), nullable=True),
    pa.field("title_embedding", pa.list_(pa.float32(), list_size=1024), nullable=True),
    pa.field("indexed_at", pa.string(), nullable=False),       # ISO timestamp
    pa.field("parser_version", pa.string(), nullable=True),
    pa.field("chunk_count", pa.int32(), nullable=False),
    pa.field("has_code", pa.bool_(), nullable=False),
    pa.field("code_repo_url", pa.string(), nullable=True),
    pa.field("code_indexed", pa.bool_(), nullable=False),
    pa.field("status", pa.string(), nullable=False),
    # complete | code_pending | chunking | pending | failed | deleted
    pa.field("error_msg", pa.string(), nullable=True),
])

# ---------------------------------------------------------------------------
# Table names
# ---------------------------------------------------------------------------

TABLE_CHUNKS = "chunks"
TABLE_MAPPING = "paper_code_mapping"
TABLE_INDEX_META = "index_meta"
