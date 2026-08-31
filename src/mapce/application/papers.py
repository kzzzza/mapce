"""Exact paper resolution, bounded section reading, and paper-scoped search."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
from typing import Any

import lancedb
from lancedb.query import FullTextOperator, MatchQuery

from mapce.paper_sources import normalize_arxiv_id
from mapce.core.embedding import embed_single
from mapce.core.vector_index import configure_vector_query, has_fts_index, has_vector_index
from mapce.db import get_connection, sql_str

logger = logging.getLogger("mapce.application.papers")

_ARXIV_LIKE = re.compile(r"(?:arxiv\s*:|https?://[^/]*arxiv\.org/|\d{4}\.\d)", re.IGNORECASE)

_META_COLUMNS = [
    "paper_id",
    "title",
    "authors",
    "arxiv_id",
    "indexed_at",
    "status",
    "code_status",
    "code_indexed",
]
_READ_COLUMNS = [
    "chunk_id",
    "chunk_type",
    "source_type",
    "paper_id",
    "content",
    "title",
    "section_path",
    "section_level",
    "chunk_index",
    "prev_chunk_id",
    "next_chunk_id",
    "figure_path",
    "figure_index",
    "table_markdown",
    "table_image",
    "table_dims",
]
_VECTOR_COLUMNS = [*_READ_COLUMNS, "_distance"]
_FTS_COLUMNS = [*_READ_COLUMNS, "_score"]


def _open_meta(db: lancedb.DBConnection) -> Any | None:
    try:
        return db.open_table("index_meta")
    except Exception:
        return None


def _query_meta(table: Any, where: str) -> dict[str, Any] | None:
    try:
        rows = table.search().where(where).select(_META_COLUMNS).limit(1).to_list()
    except Exception:
        return None
    if not rows or rows[0].get("status") == "deleted":
        return None
    return rows[0]


def _find_meta(paper_id: str, db: lancedb.DBConnection) -> dict[str, Any] | None:
    table = _open_meta(db)
    if table is None:
        return None
    return _query_meta(table, f"paper_id = {sql_str(paper_id)}")


def _resolved_payload(meta: dict[str, Any], original: str) -> dict[str, Any]:
    return {
        "status": "ok",
        "input": original,
        "paper_id": meta.get("paper_id"),
        "arxiv_id": meta.get("arxiv_id"),
        "title": meta.get("title") or "",
        "authors": meta.get("authors") or [],
        "paper_status": meta.get("status"),
        "code_status": meta.get("code_status")
        or ("indexed" if meta.get("code_indexed") else "not_checked"),
        "indexed_at": meta.get("indexed_at"),
    }


def resolve_paper(
    identifier: str,
    db: lancedb.DBConnection | None = None,
) -> dict[str, Any]:
    """Resolve an internal paper ID or arXiv reference without network/model use."""
    original = identifier.strip()
    if not original:
        return {
            "status": "error",
            "error_code": "invalid_identifier",
            "message": "Paper identifier cannot be empty.",
        }
    db = db or get_connection()
    table = _open_meta(db)
    if table is None:
        return {
            "status": "error",
            "error_code": "paper_not_indexed",
            "message": f"Paper is not indexed: {original}",
        }

    exact = _query_meta(table, f"paper_id = {sql_str(original)}")
    if exact is not None:
        return _resolved_payload(exact, original)

    normalized = normalize_arxiv_id(original)
    if normalized is None:
        error_code = "invalid_arxiv_id" if _ARXIV_LIKE.search(original) else "paper_not_indexed"
        message = (
            f"Invalid arXiv identifier: {original}"
            if error_code == "invalid_arxiv_id"
            else f"Paper is not indexed: {original}"
        )
        return {"status": "error", "error_code": error_code, "message": message}

    match = _query_meta(
        table,
        f"arxiv_id = {sql_str(normalized)} OR paper_id = {sql_str(normalized)}",
    )
    if match is None:
        return {
            "status": "error",
            "error_code": "paper_not_indexed",
            "normalized_arxiv_id": normalized,
            "message": f"Paper is not indexed: {normalized}",
        }
    return _resolved_payload(match, original)


def _selector_signature(
    paper_id: str,
    section_path: str | None,
    chunk_id: str | None,
    include_subsections: bool,
    candidate_ids: list[str],
) -> str:
    raw = json.dumps(
        [paper_id, section_path, chunk_id, include_subsections, candidate_ids],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _encode_cursor(offset: int, signature: str) -> str:
    raw = json.dumps({"offset": offset, "selector": signature}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None, signature: str) -> tuple[int, str | None]:
    if cursor is None:
        return 0, None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        offset = int(value["offset"])
        if offset < 0 or value["selector"] != signature:
            raise ValueError
        return offset, None
    except Exception:
        return 0, "Cursor is invalid or belongs to a different section selector."


def _public_chunk(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in _READ_COLUMNS if key not in {"source_type", "paper_id"}}


def read_paper_section(
    paper_id: str,
    *,
    section_path: str | None = None,
    chunk_id: str | None = None,
    include_subsections: bool = False,
    limit: int = 10,
    cursor: str | None = None,
    db: lancedb.DBConnection | None = None,
) -> dict[str, Any]:
    """Read stable, paginated paper chunks without selecting embeddings."""
    if bool(section_path) == bool(chunk_id):
        return {
            "status": "error",
            "error_code": "invalid_selector",
            "message": "Provide exactly one of section_path or chunk_id.",
        }
    if limit < 1 or limit > 20:
        return {
            "status": "error",
            "error_code": "invalid_limit",
            "message": "limit must be between 1 and 20.",
        }
    db = db or get_connection()
    if _find_meta(paper_id, db) is None:
        return {
            "status": "error",
            "error_code": "paper_not_found",
            "message": f"Paper not found: {paper_id}",
        }
    try:
        table = db.open_table("chunks")
    except Exception:
        return {
            "status": "error",
            "error_code": "content_unavailable",
            "message": f"Paper content is unavailable: {paper_id}",
        }

    pid_filter = f"paper_id = {sql_str(paper_id)} AND source_type = 'paper'"
    selected_chunk: dict[str, Any] | None = None
    paper_rows: list[dict[str, Any]] | None = None
    if chunk_id:
        try:
            # Some existing LanceDB datasets return an empty result when a
            # chunk_id equality is combined with an indexed paper_id filter,
            # even though each predicate succeeds alone. Use the paper_id
            # scalar index to fetch one paper's lightweight rows, then validate
            # the exact chunk ID in Python. Embeddings are never selected.
            paper_rows = (
                table.search()
                .where(pid_filter, prefilter=True)
                .select(_READ_COLUMNS)
                .limit(10000)
                .to_list()
            )
        except Exception:
            paper_rows = []
        selected_chunk = next(
            (row for row in paper_rows if row.get("chunk_id") == chunk_id),
            None,
        )
        if selected_chunk is None:
            return {
                "status": "error",
                "error_code": "chunk_not_found",
                "message": f"Chunk does not belong to paper {paper_id}: {chunk_id}",
            }
        if selected_chunk.get("chunk_type") != "paper_l2":
            candidates = [selected_chunk]
        else:
            section_path = selected_chunk.get("section_path") or ""

    if section_path is not None and (selected_chunk is None or selected_chunk.get("chunk_type") == "paper_l2"):
        if paper_rows is None:
            try:
                all_rows = (
                    table.search()
                    .where(f"{pid_filter} AND chunk_type IN ('paper_l2', 'paper_l3')", prefilter=True)
                    .select(_READ_COLUMNS)
                    .limit(10000)
                    .to_list()
                )
            except Exception:
                all_rows = []
        else:
            all_rows = [
                row for row in paper_rows
                if row.get("chunk_type") in {"paper_l2", "paper_l3"}
            ]
        candidates = [
            row
            for row in all_rows
            if row.get("section_path") == section_path
            or (
                include_subsections
                and bool(section_path)
                and str(row.get("section_path") or "").startswith(section_path + " > ")
            )
        ]
        l3_rows = [row for row in candidates if row.get("chunk_type") == "paper_l3"]
        if l3_rows:
            candidates = l3_rows
        elif selected_chunk is not None:
            candidates = [selected_chunk]

    if not candidates:
        return {
            "status": "error",
            "error_code": "section_not_found",
            "message": f"Section not found in paper {paper_id}: {section_path}",
        }

    candidates.sort(
        key=lambda row: (
            int(row.get("chunk_index") or 0),
            str(row.get("section_path") or ""),
            str(row.get("chunk_id") or ""),
        )
    )
    signature = _selector_signature(
        paper_id,
        section_path,
        chunk_id,
        include_subsections,
        [str(row.get("chunk_id") or "") for row in candidates],
    )
    offset, cursor_error = _decode_cursor(cursor, signature)
    if cursor_error:
        return {"status": "error", "error_code": "invalid_cursor", "message": cursor_error}
    page = candidates[offset : offset + limit]
    next_offset = offset + len(page)
    next_cursor = (
        _encode_cursor(next_offset, signature) if next_offset < len(candidates) else None
    )
    return {
        "status": "ok",
        "paper_id": paper_id,
        "section_path": section_path,
        "count": len(page),
        "total_chunks": len(candidates),
        "next_cursor": next_cursor,
        "chunks": [_public_chunk(row) for row in page],
    }


def search_paper_content(
    paper_id: str,
    query: str,
    *,
    top_k: int = 10,
    db: lancedb.DBConnection | None = None,
) -> dict[str, Any]:
    """Retrieve multiple relevant chunks strictly within one indexed paper."""
    if not query.strip():
        return {"status": "error", "error_code": "invalid_query", "message": "query cannot be empty."}
    if top_k < 1 or top_k > 20:
        return {
            "status": "error",
            "error_code": "invalid_top_k",
            "message": "top_k must be between 1 and 20.",
        }
    db = db or get_connection()
    if _find_meta(paper_id, db) is None:
        return {
            "status": "error",
            "error_code": "paper_not_found",
            "count": 0,
            "results": [],
            "message": f"Paper not found: {paper_id}",
        }
    try:
        table = db.open_table("chunks")
        query_vector = embed_single(query)
        where = (
            f"paper_id = {sql_str(paper_id)} AND source_type = 'paper' "
            "AND chunk_type IN ('paper_l2', 'paper_l3', 'figure', 'table')"
        )
        candidate_limit = max(50, top_k * 10)
        dense_query = (
            table.search(query_vector)
            .where(where, prefilter=True)
            .select(_VECTOR_COLUMNS)
            .limit(candidate_limit)
        )
        dense_query = configure_vector_query(dense_query, indexed=has_vector_index(table))
        dense_rows = dense_query.to_list()
    except Exception:
        logger.exception("Paper-scoped vector search failed")
        return {
            "status": "error",
            "error_code": "vector_search_failed",
            "count": 0,
            "results": [],
            "message": "Vector search failed; no search results were returned.",
        }

    fts_rows: list[dict[str, Any]] = []
    if has_fts_index(table):
        try:
            fts_rows = (
                table.search(
                    MatchQuery(
                        query.strip(),
                        "fulltext_search",
                        fuzziness=0,
                        operator=FullTextOperator.OR,
                    )
                )
                .where(where, prefilter=True)
                .select(_FTS_COLUMNS)
                .limit(candidate_limit)
                .to_list()
            )
        except Exception:
            logger.warning("Paper-scoped full-text search failed; using dense results", exc_info=True)

    short_acronym = bool(re.fullmatch(r"[A-Z][A-Z0-9-]{1,7}", query.strip()))
    signals = (("dense_fine", 1.0, dense_rows), ("fulltext", 2.0 if short_acronym else 1.0, fts_rows))
    scores: dict[str, float] = {}
    dense_similarity: dict[str, float] = {}
    lexical_score: dict[str, float] = {}
    sources: dict[str, set[str]] = {}
    rows_by_id: dict[str, dict[str, Any]] = {}
    for source, weight, rows in signals:
        seen: set[str] = set()
        rank = 0
        for row in rows:
            chunk_id = row.get("chunk_id")
            if not chunk_id or chunk_id in seen:
                continue
            seen.add(chunk_id)
            rank += 1
            scores[chunk_id] = scores.get(chunk_id, 0.0) + weight / (60 + rank)
            sources.setdefault(chunk_id, set()).add(source)
            rows_by_id.setdefault(chunk_id, row)
            if source == "dense_fine":
                distance = row.get("_distance")
                dense_similarity[chunk_id] = 1.0 / (1.0 + float(distance or 0.0))
            else:
                lexical_score[chunk_id] = float(row.get("_score") or 0.0)

    ordered = sorted(
        scores,
        key=lambda chunk_id: (
            -scores[chunk_id],
            -dense_similarity.get(chunk_id, 0.0),
            -lexical_score.get(chunk_id, 0.0),
            chunk_id,
        ),
    )[:top_k]
    results = []
    for chunk_id in ordered:
        row = _public_chunk(rows_by_id[chunk_id])
        row["score"] = scores[chunk_id]
        row["retrieval_sources"] = sorted(
            sources[chunk_id], key=lambda item: 0 if item == "fulltext" else 1
        )
        results.append(row)
    return {
        "status": "ok" if results else "no_results",
        "paper_id": paper_id,
        "query": query,
        "count": len(results),
        "results": results,
        "message": None if results else "No matching content found in this paper.",
    }
