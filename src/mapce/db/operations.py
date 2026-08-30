"""CRUD operations for LanceDB tables.

Thin wrappers over LanceDB's Python API — the caller handles embedding
and chunk construction; this module only deals with raw table I/O.
"""

from __future__ import annotations

import uuid
from typing import Any

import lancedb
import pyarrow as pa

from ._sql import sql_str
from .schema import TABLE_CHUNKS, TABLE_CODE_REPOS, TABLE_MAPPING, TABLE_INDEX_META


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
    # Existing IVF/scalar indices do not immediately cover appended rows in
    # LanceDB OSS. Keep the index current after every paper/code batch; the
    # helper is best-effort so a maintenance issue never rolls back valid data.
    from mapce.core.vector_index import maintain_vector_indices_after_write
    maintain_vector_indices_after_write(table)
    return len(rows)


def delete_chunks_by_paper(table: Any, paper_id: str) -> int:
    """Delete all chunks for a paper. Returns count deleted (approx)."""
    before = table.count_rows()
    table.delete(f"paper_id = {sql_str(paper_id)}")
    after = table.count_rows()
    return before - after


def delete_chunks_by_repo(table: Any, paper_id: str, repo_name: str) -> int:
    """Delete code chunks for a specific repo under a single owning paper."""
    before = table.count_rows()
    table.delete(f"paper_id = {sql_str(paper_id)} AND repo_name = {sql_str(repo_name)}")
    after = table.count_rows()
    return before - after


def delete_chunks_by_repo_url(table: Any, paper_id: str, repo_url: str) -> int:
    """Delete code chunks for one normalized repository association."""
    before = table.count_rows()
    table.delete(f"paper_id = {sql_str(paper_id)} AND repo_url = {sql_str(repo_url)}")
    after = table.count_rows()
    return before - after


def delete_legacy_chunks_by_repo(table: Any, paper_id: str, repo_name: str) -> int:
    """Delete old code chunks that predate repository URL propagation."""
    before = table.count_rows()
    table.delete(
        f"paper_id = {sql_str(paper_id)} AND repo_name = {sql_str(repo_name)} "
        "AND repo_url IS NULL"
    )
    after = table.count_rows()
    return before - after


def delete_chunks_by_repo_name(table: Any, repo_name: str) -> int:
    """Delete all code chunks for a repo regardless of owning paper_id.

    Code chunks are physically stored under whichever paper_id first indexed
    the repo, so deleting "this paper's copy" can miss the real chunks. When a
    repo is no longer referenced by any paper, this removes the single physical
    copy by repo_name alone.
    """
    before = table.count_rows()
    table.delete(f"repo_name = {sql_str(repo_name)}")
    after = table.count_rows()
    return before - after


def count_chunks_for_paper(table: Any, paper_id: str) -> int:
    """Count chunks belonging to a paper."""
    return table.count_rows(f"paper_id = {sql_str(paper_id)}")


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
    table.delete(f"paper_id = {sql_str(paper_id)}")
    after = table.count_rows()
    return before - after


# ---------------------------------------------------------------------------
# paper_code_repos
# ---------------------------------------------------------------------------

def init_code_repos(db: lancedb.DBConnection) -> Any:
    from .schema import CODE_REPOS_SCHEMA
    return _ensure_table(db, TABLE_CODE_REPOS, CODE_REPOS_SCHEMA)


def upsert_code_repo(table: Any, row: dict[str, Any]) -> None:
    """Idempotently replace one paper/repository association."""
    table.delete(f"association_id = {sql_str(row['association_id'])}")
    table.add([row])


def get_code_repo(table: Any, paper_id: str, repo_url: str) -> dict | None:
    try:
        rows = (
            table.search()
            .where(f"paper_id = {sql_str(paper_id)} AND repo_url = {sql_str(repo_url)}")
            .limit(1)
            .to_list()
        )
        return rows[0] if rows else None
    except Exception:
        return None


def list_code_repos(table: Any, paper_id: str | None = None) -> list[dict]:
    try:
        query = table.search()
        if paper_id is not None:
            query = query.where(f"paper_id = {sql_str(paper_id)}")
        return query.to_list()
    except Exception:
        return []


def delete_code_repos_by_paper(table: Any, paper_id: str) -> int:
    before = table.count_rows()
    table.delete(f"paper_id = {sql_str(paper_id)}")
    after = table.count_rows()
    return before - after


# ---------------------------------------------------------------------------
# index_meta
# ---------------------------------------------------------------------------

def init_index_meta(db: lancedb.DBConnection) -> Any:
    from .schema import INDEX_META_SCHEMA
    return _ensure_table(db, TABLE_INDEX_META, INDEX_META_SCHEMA)


def ensure_index_meta_code_columns(table: Any) -> Any:
    """Add code-state columns to a legacy index_meta table.

    This function is intentionally explicit. Read-only callers and migration
    dry-runs can open the legacy table without changing it.
    """
    names = set(table.schema.names)
    if "code_status" not in names:
        table.add_columns({"code_status": "'not_checked'"})
        # Preserve legacy meaning immediately. This explicit schema upgrade may
        # be triggered before the formal migration is applied.
        table.update(where="code_indexed = true", values={"code_status": "indexed"})
        table.update(
            where="has_code = true AND code_indexed = false",
            values={"code_status": "pending"},
        )
        table.update(
            where="status = 'code_pending' AND code_indexed = false",
            values={"code_status": "pending"},
        )
    names = set(table.schema.names)
    if "code_checked_at" not in names:
        table.add_columns({"code_checked_at": "CAST(NULL AS STRING)"})
    return table


def ensure_index_meta_metadata_columns(table: Any) -> Any:
    """Add structured paper-metadata columns to a legacy index_meta table."""
    if "authors" not in set(table.schema.names):
        # Lance/DataFusion cannot CAST directly to a list type. Build a typed
        # one-item list and slice it to an empty list instead.
        table.add_columns({
            "authors": "array_slice(make_array(CAST(NULL AS STRING)), 1, 0)"
        })
    return table


def upsert_meta(table: Any, row: dict[str, Any]) -> None:
    """Insert or update index metadata for a paper."""
    # LanceDB doesn't have native upsert; delete-then-insert
    table.delete(f"paper_id = {sql_str(row['paper_id'])}")
    table.add([row])


def get_meta(table: Any, paper_id: str) -> dict | None:
    """Get index metadata for a paper."""
    try:
        result = table.search().where(f"paper_id = {sql_str(paper_id)}").limit(1).to_list()
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
