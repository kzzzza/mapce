"""Async handler functions for MCP tools.

Each function takes keyword arguments matching the tool's inputSchema
and returns a JSON string.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("mapce.mcp")


def _vector_search_error_response() -> str:
    """Return a stable MCP response without exposing misleading results."""
    return json.dumps({
        "status": "error",
        "error_code": "vector_search_failed",
        "count": 0,
        "results": [],
        "message": "Vector search failed; no search results were returned.",
    })


# ---------------------------------------------------------------------------
# search_papers
# ---------------------------------------------------------------------------

async def search_papers(
    query: str,
    top_k: int = 10,
    year_min: int | None = None,
    year_max: int | None = None,
    venue: str | None = None,
) -> str:
    """Search indexed papers using 4-stage progressive retrieval."""
    from mapce.core.retrieval import VectorSearchError
    from mapce.core.retrieval import search_papers as _search_papers

    try:
        results, intent = _search_papers(
            query=query, top_k=top_k,
            year_min=year_min, year_max=year_max, venue=venue,
        )
    except VectorSearchError:
        logger.exception("Paper vector search failed")
        return _vector_search_error_response()

    if not results:
        return json.dumps({
            "status": "no_results",
            "intent": intent.intent,
            "sub_type": intent.sub_type,
            "results": [],
            "message": "No matching papers found.",
        })

    return json.dumps({
        "status": "ok",
        "intent": intent.intent,
        "sub_type": intent.sub_type,
        "count": len(results),
        "results": [
            {
                "paper_id": r.paper_id,
                "title": r.title,
                "authors": r.authors[:5],
                "year": r.year,
                "venue": r.venue,
                "chunk_type": r.chunk_type,
                "section_path": r.section_path,
                "content": r.content[:2000],
                "figure_path": r.figure_path,
            }
            for r in results
        ],
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# search_code
# ---------------------------------------------------------------------------

async def search_code(
    query: str,
    top_k: int = 10,
    repo_name: str | None = None,
    paper_id: str | None = None,
    repo_url: str | None = None,
) -> str:
    """Search indexed code chunks."""
    from mapce.core.code_repositories import (
        get_repository_associations,
        normalize_github_url,
    )
    from mapce.core.retrieval import VectorSearchError
    from mapce.core.retrieval import search_code as _search_code
    from mapce.db import get_connection, get_meta, init_index_meta

    normalized_repo_url = None
    if repo_url is not None:
        normalized_repo_url = normalize_github_url(repo_url)
        if normalized_repo_url is None:
            return json.dumps({
                "status": "error",
                "error_code": "invalid_repository_url",
                "count": 0,
                "results": [],
                "message": "repo_url must be a GitHub owner/repo URL.",
            })

    if paper_id is not None:
        db = get_connection()
        meta = get_meta(init_index_meta(db), paper_id)
        if meta is None or meta.get("status") == "deleted":
            return json.dumps({
                "status": "error", "error_code": "paper_not_found",
                "count": 0, "results": [], "message": f"Paper not found: {paper_id}",
            })
        repositories = get_repository_associations(paper_id, db)
        if not repositories and meta.get("code_indexed") and meta.get("code_repo_url"):
            legacy_url = normalize_github_url(meta["code_repo_url"])
            if legacy_url is not None:
                repositories = [{
                    "paper_id": paper_id,
                    "repo_url": legacy_url,
                    "repo_name": legacy_url.rsplit("/", 1)[-1],
                    "source": "legacy",
                    "confidence": "high",
                    "is_primary": True,
                    "status": "indexed",
                    "evidence": "Legacy index_meta compatibility view",
                }]
        code_status = meta.get("code_status") or (
            "indexed" if meta.get("code_indexed") else
            "pending" if meta.get("status") == "code_pending" else "not_checked"
        )
        if code_status == "no_code":
            return json.dumps({
                "status": "error", "error_code": "no_code_repository",
                "code_status": code_status, "count": 0, "results": [],
                "repositories": repositories,
                "message": "No repository was found in the paper or arXiv metadata.",
            }, ensure_ascii=False)
        matching = repositories
        if normalized_repo_url is not None:
            matching = [row for row in repositories if row.get("repo_url") == normalized_repo_url]
        if code_status != "indexed" or not any(row.get("status") == "indexed" for row in matching):
            return json.dumps({
                "status": "error", "error_code": "code_not_indexed",
                "code_status": code_status, "count": 0, "results": [],
                "repositories": repositories,
                "message": "The paper's code repository is not indexed yet.",
            }, ensure_ascii=False)

    try:
        results, intent = _search_code(
            query=query,
            top_k=top_k,
            repo_name=repo_name,
            paper_id=paper_id,
            repo_url=normalized_repo_url,
        )
    except VectorSearchError:
        logger.exception("Code vector search failed")
        return _vector_search_error_response()

    if not results:
        return json.dumps({
            "status": "no_results",
            "results": [],
            "message": "No matching code found.",
        })

    return json.dumps({
        "status": "ok",
        "count": len(results),
        "results": [
            {
                "chunk_id": r.chunk_id,
                "paper_id": r.paper_id,
                "repo_name": r.repo_name,
                "repo_url": r.repo_url,
                "file_path": r.file_path,
                "language": r.language,
                "symbol_name": getattr(r, 'symbol_name', None),
                "chunk_type": r.chunk_type,
                "content": r.content[:2000],
            }
            for r in results
        ],
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# index_paper
# ---------------------------------------------------------------------------

async def index_paper(
    source: str,
    source_type: str = "local",
    language: str = "en",
) -> str:
    """Index a paper from a local PDF path, arXiv ID, or URL."""
    from mapce.core.indexing import index_paper as _index_paper
    from mapce.core.indexing import index_paper_from_arxiv
    from mapce.core.code_repositories import get_repository_associations
    from mapce.db import get_connection, get_meta, init_index_meta

    if source_type == "arxiv":
        paper_id = index_paper_from_arxiv(arxiv_id=source, language=language)
    elif source_type in ("local", "url"):
        pdf_path = Path(source).expanduser()
        if not pdf_path.exists():
            return json.dumps({"status": "error", "message": f"File not found: {source}"})
        paper_id = _index_paper(pdf_path=pdf_path, language=language)
    else:
        return json.dumps({"status": "error", "message": f"Unknown source_type: {source_type}"})

    db = get_connection()
    meta = get_meta(init_index_meta(db), paper_id) or {}
    repositories = get_repository_associations(paper_id, db)
    return json.dumps({
        "status": "ok",
        "paper_id": paper_id,
        "code_status": meta.get("code_status", "not_checked"),
        "code_repositories": repositories,
        "message": f"Paper indexed: {paper_id}",
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# index_code
# ---------------------------------------------------------------------------

async def index_code(
    repo_url: str,
    paper_id: str,
) -> str:
    """Index a user-provided repository after validating the paper."""
    from mapce.core.code_indexing import (
        CodeIndexingError,
        InvalidRepositoryURLError,
        PaperNotFoundError,
        index_code_repository,
    )
    try:
        result = index_code_repository(repo_url, paper_id, source="user", confidence="high", score=9)
        return json.dumps({
            "status": "ok",
            **result,
            "message": f"Indexed {result['chunk_count']} chunks from {result['repo_name']}.",
        }, ensure_ascii=False)
    except PaperNotFoundError as exc:
        return json.dumps({"status": "error", "error_code": "paper_not_found", "message": str(exc)})
    except InvalidRepositoryURLError as exc:
        return json.dumps({"status": "error", "error_code": "invalid_repository_url", "message": str(exc)})
    except CodeIndexingError as exc:
        return json.dumps({"status": "error", "error_code": "code_index_failed", "message": str(exc)})


# ---------------------------------------------------------------------------
# list_indexed_papers
# ---------------------------------------------------------------------------

async def list_indexed_papers() -> str:
    """List all indexed papers."""
    from mapce.db import get_connection, init_index_meta, list_all_meta

    db = get_connection()
    meta_table = init_index_meta(db)
    papers = list_all_meta(meta_table)

    if not papers:
        return json.dumps({"status": "ok", "count": 0, "papers": []})

    return json.dumps({
        "status": "ok",
        "count": len(papers),
        "papers": [
            {
                "paper_id": p["paper_id"],
                "title": p["title"][:100],
                "arxiv_id": p.get("arxiv_id"),
                "indexed_at": p["indexed_at"],
                "chunk_count": p["chunk_count"],
                "has_code": p["has_code"],
                "code_indexed": p["code_indexed"],
                "code_status": p.get(
                    "code_status",
                    "indexed" if p.get("code_indexed") else "not_checked",
                ),
                "status": p["status"],
            }
            for p in papers
        ],
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# get_paper_overview
# ---------------------------------------------------------------------------

async def get_paper_overview(paper_id: str) -> str:
    """Get paper overview."""
    from mapce.core.retrieval import get_paper_overview as _get_overview

    overview = _get_overview(paper_id)
    if overview is None:
        return json.dumps({"status": "error", "message": f"Paper not found: {paper_id}"})

    return json.dumps({"status": "ok", **overview}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# delete_paper
# ---------------------------------------------------------------------------

async def delete_paper(paper_id: str) -> str:
    """Delete a paper and all its chunks."""
    from mapce.core.incremental import delete_paper_safe

    summary = delete_paper_safe(paper_id)
    return json.dumps({
        "status": "ok",
        **summary,
        "message": f"Deleted paper {paper_id}: {summary['chunks_deleted']} chunks, {summary['mappings_deleted']} mappings.",
    })


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------

async def get_stats() -> str:
    """Get index statistics."""
    from mapce.db import get_connection, init_chunks, init_index_meta
    from mapce.db.operations import list_all_meta

    db = get_connection()
    chunks_table = init_chunks(db)
    meta_table = init_index_meta(db)

    papers = list_all_meta(meta_table)
    total_chunks = chunks_table.count_rows() if chunks_table else 0
    papers_with_code = sum(1 for p in papers if p.get("code_indexed"))
    code_status_counts: dict[str, int] = {}
    for paper in papers:
        status = paper.get("code_status") or (
            "indexed" if paper.get("code_indexed") else "not_checked"
        )
        code_status_counts[status] = code_status_counts.get(status, 0) + 1

    return json.dumps({
        "status": "ok",
        "total_papers": len(papers),
        "papers_with_code": papers_with_code,
        "code_status_distribution": code_status_counts,
        "total_chunks": total_chunks,
    }, ensure_ascii=False)
