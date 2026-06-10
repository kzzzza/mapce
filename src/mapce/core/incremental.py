"""Incremental indexing support.

Handles deduplication, state tracking, version updates, and safe deletion
so that papers and code can be added, updated, and removed without
rebuilding the entire index.
"""

from __future__ import annotations

from typing import Any

import lancedb
import numpy as np

from mapce.core.embedding import embed_single
from mapce.db import get_connection, init_index_meta
from mapce.db.operations import get_meta, list_all_meta, upsert_meta


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def check_duplicate(
    arxiv_id: str | None = None,
    doi: str | None = None,
    title: str = "",
    db: lancedb.DBConnection | None = None,
) -> tuple[bool, str | None]:
    """Check if a paper already exists in the index.

    Three-layer dedup strategy:
      1. arxiv_id exact match (fastest, O(1) via filter)
      2. doi exact match
      3. title embedding cosine similarity > 0.95

    Args:
        arxiv_id: arXiv paper ID.
        doi: DOI string.
        title: Paper title.
        db: Optional LanceDB connection.

    Returns:
        (is_duplicate, existing_paper_id_or_None).
    """
    if db is None:
        db = get_connection()
    try:
        meta_table = init_index_meta(db)
    except Exception:
        return False, None

    # Layer 1: arxiv_id exact match
    if arxiv_id:
        existing = get_meta(meta_table, arxiv_id)
        if existing and existing.get("status") != "deleted":
            return True, arxiv_id

    # Layer 2: doi exact match
    if doi:
        doi_id = "doi_" + doi.lower().replace("/", "_")
        existing = get_meta(meta_table, doi_id)
        if existing and existing.get("status") != "deleted":
            return True, doi_id

    # Layer 3: title embedding similarity
    if title:
        title_emb = embed_single(title)
        all_papers = list_all_meta(meta_table)

        best_score = 0.0
        best_id: str | None = None

        for paper in all_papers:
            existing_emb = paper.get("title_embedding")
            if existing_emb is None:
                continue
            score = _cosine_similarity(title_emb, existing_emb)
            if score > best_score:
                best_score = score
                best_id = paper["paper_id"]

        if best_score > 0.95 and best_id:
            return True, best_id

    return False, None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    norm_a = float(np.linalg.norm(va))
    norm_b = float(np.linalg.norm(vb))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (norm_a * norm_b))


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

VALID_STATES = {"pending", "chunking", "complete", "code_pending", "failed", "deleted"}

TERMINAL_STATES = {"complete", "failed", "deleted"}


def transition_state(
    paper_id: str,
    new_state: str,
    error_msg: str | None = None,
    db: lancedb.DBConnection | None = None,
) -> bool:
    """Advance a paper's indexing state.

    Valid transitions (any → next):
      pending → chunking → complete
      pending → chunking → code_pending → complete
      any → failed
      any → deleted

    Args:
        paper_id: The paper to update.
        new_state: Target state from VALID_STATES.
        error_msg: Error description if transitioning to 'failed'.
        db: Optional LanceDB connection.

    Returns:
        True if state was updated, False if paper not found.
    """
    if new_state not in VALID_STATES:
        raise ValueError(f"Invalid state: {new_state}. Must be one of {VALID_STATES}")

    if db is None:
        db = get_connection()
    meta_table = init_index_meta(db)

    meta = get_meta(meta_table, paper_id)
    if meta is None:
        return False

    meta["status"] = new_state
    if error_msg:
        meta["error_msg"] = error_msg
    elif new_state != "failed":
        meta["error_msg"] = None

    upsert_meta(meta_table, meta)
    return True


def get_pending_papers(db: lancedb.DBConnection | None = None) -> list[dict[str, Any]]:
    """Get all papers that are not in a terminal state."""
    if db is None:
        db = get_connection()
    meta_table = init_index_meta(db)
    all_papers = list_all_meta(meta_table)
    return [p for p in all_papers if p.get("status") not in TERMINAL_STATES]


def get_papers_needing_code(db: lancedb.DBConnection | None = None) -> list[dict[str, Any]]:
    """Get papers that have code repos detected but not yet indexed."""
    if db is None:
        db = get_connection()
    meta_table = init_index_meta(db)
    all_papers = list_all_meta(meta_table)
    return [
        p for p in all_papers
        if p.get("status") == "code_pending" or (p.get("has_code") and not p.get("code_indexed"))
    ]


# ---------------------------------------------------------------------------
# Version update (re-index a paper with new version)
# ---------------------------------------------------------------------------

def reindex_paper(
    paper_id: str,
    db: lancedb.DBConnection | None = None,
) -> bool:
    """Prepare a paper for re-indexing by deleting existing chunks.

    The actual re-indexing is done by calling index_paper again.

    Args:
        paper_id: Paper to prepare for re-index.
        db: Optional LanceDB connection.

    Returns:
        True if paper was found and chunks deleted.
    """
    if db is None:
        db = get_connection()

    from mapce.db.operations import delete_chunks_by_paper, delete_mappings_by_paper

    meta_table = init_index_meta(db)
    meta = get_meta(meta_table, paper_id)
    if meta is None:
        return False

    # Delete existing chunks and mappings
    delete_chunks_by_paper(db.open_table("chunks"), paper_id)
    delete_mappings_by_paper(db.open_table("paper_code_mapping"), paper_id)

    # Update meta to pending so the re-index can set it to complete
    meta["status"] = "pending"
    meta["chunk_count"] = 0
    meta["code_indexed"] = False
    upsert_meta(meta_table, meta)

    return True


# ---------------------------------------------------------------------------
# Safe deletion
# ---------------------------------------------------------------------------

def delete_paper_safe(
    paper_id: str,
    db: lancedb.DBConnection | None = None,
) -> dict[str, Any]:
    """Safely delete a paper and manage cascading effects on shared code.

    - Delete all paper chunks
    - Delete Paper↔Code mappings
    - Check if code chunks are shared with other papers
    - If not shared, delete code chunks too
    - Mark index_meta as deleted

    Args:
        paper_id: Paper to delete.
        db: Optional LanceDB connection.

    Returns:
        Summary dict of what was deleted.
    """
    if db is None:
        db = get_connection()

    from mapce.db import sql_str
    from mapce.db.operations import (
        delete_chunks_by_paper,
        delete_chunks_by_repo_name,
        delete_mappings_by_paper,
        get_meta,
    )

    chunks_table = db.open_table("chunks")
    mapping_table = db.open_table("paper_code_mapping")
    meta_table = init_index_meta(db)

    meta = get_meta(meta_table, paper_id)
    repo_name = meta.get("code_repo_url", "").rstrip("/").split("/")[-1].replace(".git", "") if meta else ""

    summary = {
        "paper_id": paper_id,
        "chunks_deleted": 0,
        "code_chunks_deleted": 0,
        "mappings_deleted": 0,
    }

    # Delete paper chunks
    summary["chunks_deleted"] = delete_chunks_by_paper(chunks_table, paper_id)

    # Delete mappings
    summary["mappings_deleted"] = delete_mappings_by_paper(mapping_table, paper_id)

    # Check if code chunks are shared — if not, delete them too.
    # NOTE: code chunks are physically stored under whichever paper_id first
    # indexed the repo, so deletion must key on repo_name alone (not this
    # paper_id) to remove the single physical copy. Cross-paper *retrieval* of
    # shared code is a separate, deeper limitation (code_search filters by
    # paper_id) and is intentionally out of scope here.
    if repo_name:
        # Count how many *other* papers reference this repo
        try:
            remaining = (
                mapping_table.search()
                .where(f"repo_name = {sql_str(repo_name)} AND paper_id != {sql_str(paper_id)}")
                .to_list()
            )
        except Exception:
            remaining = []

        if not remaining:
            # No other paper uses this repo — safe to delete its code chunks
            summary["code_chunks_deleted"] = delete_chunks_by_repo_name(chunks_table, repo_name)

    # Mark as deleted in metadata
    if meta:
        meta["status"] = "deleted"
        upsert_meta(meta_table, meta)

    return summary


# ---------------------------------------------------------------------------
# Periodic maintenance
# ---------------------------------------------------------------------------

def compact_database(db: lancedb.DBConnection | None = None) -> None:
    """Compact LanceDB tables to reclaim disk space after deletions.

    Call this periodically (e.g., after batch deletions) to optimize storage.
    """
    if db is None:
        db = get_connection()

    for table_name in ["chunks", "paper_code_mapping", "index_meta"]:
        try:
            table = db.open_table(table_name)
            table.compact_files()
        except Exception:
            pass


def re_embed_all(
    db: lancedb.DBConnection | None = None,
) -> int:
    """Recompute embeddings for all chunks. Use after switching embedding models.

    This is the only operation that requires touching every chunk.

    Returns:
        Number of chunks re-embedded.
    """
    from mapce.core.embedding import embed
    from mapce.db import sql_str

    if db is None:
        db = get_connection()

    try:
        table = db.open_table("chunks")
    except Exception:
        return 0

    all_rows = table.search().to_list()
    if not all_rows:
        return 0

    contents = [r["content"] for r in all_rows]
    new_embeddings = embed(contents)

    # LanceDB doesn't support in-place updates efficiently, so we
    # delete all and re-insert with new embeddings.
    # For large indexes, batch this by paper_id to reduce memory pressure.

    updated = []
    for row, emb in zip(all_rows, new_embeddings):
        row["embedding"] = emb
        updated.append(row)

    # Delete and re-add — LanceDB versioning keeps old data until compact
    for row in all_rows:
        table.delete(f"chunk_id = {sql_str(row['chunk_id'])}")
    table.add(updated)

    return len(updated)
