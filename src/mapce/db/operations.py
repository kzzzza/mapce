"""CRUD operations for LanceDB tables.

Thin wrappers over LanceDB's Python API — the caller handles embedding
and chunk construction; this module only deals with raw table I/O.
"""

from __future__ import annotations

import uuid
from typing import Any

import lancedb
import pyarrow as pa

from .schema import TABLE_CHUNKS, TABLE_MAPPING, TABLE_INDEX_META


def _ensure_table(db: lancedb.DBConnection, name: str, schema: pa.Schema) -> Any:
    """Get or create a LanceDB table."""
    try:
        return db.open_table(name)
    except Exception:
        return db.create_table(name, schema=schema)


# ---------------------------------------------------------------------------
# chunks
# ---------------------------------------------------------------------------

def init_chunks(db: lancedb.DBConnection) -> Any:
    from .schema import CHUNKS_SCHEMA
    return _ensure_table(db, TABLE_CHUNKS, CHUNKS_SCHEMA)


def insert_chunks(table: Any, rows: list[dict[str, Any]]) -> int:
    """Insert chunk rows. Returns count inserted."""
    if not rows:
        return 0
    table.add(rows)
    return len(rows)


def delete_chunks_by_paper(table: Any, paper_id: str) -> int:
    """Delete all chunks for a paper. Returns count deleted (approx)."""
    before = table.count_rows()
    table.delete(f"paper_id = '{paper_id}'")
    after = table.count_rows()
    return before - after


def delete_chunks_by_repo(table: Any, paper_id: str, repo_name: str) -> int:
    """Delete code chunks for a specific repo under a paper."""
    before = table.count_rows()
    table.delete(f"paper_id = '{paper_id}' AND repo_name = '{repo_name}'")
    after = table.count_rows()
    return before - after


def count_chunks_for_paper(table: Any, paper_id: str) -> int:
    """Count chunks belonging to a paper."""
    return table.count_rows(f"paper_id = '{paper_id}'")


# ---------------------------------------------------------------------------
# paper_code_mapping
# ---------------------------------------------------------------------------

def init_mapping(db: lancedb.DBConnection) -> Any:
    from .schema import MAPPING_SCHEMA
    return _ensure_table(db, TABLE_MAPPING, MAPPING_SCHEMA)


def insert_mappings(table: Any, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    table.add(rows)
    return len(rows)


def delete_mappings_by_paper(table: Any, paper_id: str) -> int:
    before = table.count_rows()
    table.delete(f"paper_id = '{paper_id}'")
    after = table.count_rows()
    return before - after


# ---------------------------------------------------------------------------
# index_meta
# ---------------------------------------------------------------------------

def init_index_meta(db: lancedb.DBConnection) -> Any:
    from .schema import INDEX_META_SCHEMA
    return _ensure_table(db, TABLE_INDEX_META, INDEX_META_SCHEMA)


def upsert_meta(table: Any, row: dict[str, Any]) -> None:
    """Insert or update index metadata for a paper."""
    # LanceDB doesn't have native upsert; delete-then-insert
    table.delete(f"paper_id = '{row['paper_id']}'")
    table.add([row])


def get_meta(table: Any, paper_id: str) -> dict | None:
    """Get index metadata for a paper."""
    try:
        result = table.search().where(f"paper_id = '{paper_id}'").limit(1).to_list()
        return result[0] if result else None
    except Exception:
        return None


def list_all_meta(table: Any) -> list[dict]:
    """List all non-deleted index entries."""
    try:
        return table.search().where("status != 'deleted'").to_list()
    except Exception:
        return table.search().to_list()


def _make_id() -> str:
    return uuid.uuid4().hex[:12]
