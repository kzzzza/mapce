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
                "score": r.score,
                "retrieval_sources": r.retrieval_sources,
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
    from mapce.paper_sources import PaperSourceError, validate_paper_source

    try:
        detected = validate_paper_source(source, source_type)
    except PaperSourceError as exc:
        return json.dumps({
            "status": "error",
            "error_code": exc.error_code,
            "message": str(exc),
        })

    from mapce.core.indexing import index_paper as _index_paper
    from mapce.core.indexing import index_paper_from_arxiv
    from mapce.core.indexing import index_paper_from_url
    from mapce.core.code_repositories import get_repository_associations
    from mapce.db import get_connection, get_meta, init_index_meta

    if source_type == "arxiv":
        paper_id = index_paper_from_arxiv(
            arxiv_id=detected.normalized_source,
            language=language,
        )
    elif source_type == "local":
        pdf_path = Path(detected.normalized_source)
        if not pdf_path.is_file():
            return json.dumps({
                "status": "error",
                "error_code": "file_not_found",
                "message": f"File not found: {source}",
            })
        if pdf_path.suffix.lower() != ".pdf":
            return json.dumps({
                "status": "error",
                "error_code": "invalid_local_pdf",
                "message": f"Local paper source is not a PDF file: {source}",
            })
        paper_id = _index_paper(pdf_path=pdf_path, language=language)
    elif source_type == "url":
        paper_id = index_paper_from_url(
            url=detected.normalized_source,
            language=language,
        )
    else:
        return json.dumps({
            "status": "error",
            "error_code": "invalid_source_type",
            "message": f"Unknown source_type: {source_type}",
        })

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
    papers = list_all_meta(meta_table, columns=[
        "paper_id", "title", "authors", "arxiv_id", "indexed_at",
        "chunk_count", "has_code", "code_indexed", "code_status", "status",
    ])

    paper_details: dict[str, dict] = {}
    try:
        l1_rows = (
            db.open_table("chunks")
            .search()
            .where("chunk_type = 'paper_l1'", prefilter=True)
            .select(["paper_id", "year", "venue"])
            .limit(10000)
            .to_list()
        )
        for row in l1_rows:
            paper_id = str(row.get("paper_id") or "")
            if not paper_id:
                continue
            details = paper_details.setdefault(paper_id, {"year": None, "venue": None})
            if details["year"] is None and row.get("year") is not None:
                details["year"] = row.get("year")
            if not details["venue"] and row.get("venue"):
                details["venue"] = row.get("venue")
    except Exception:
        logger.warning("Failed to load paper year/venue metadata", exc_info=True)

    if not papers:
        return json.dumps({"status": "ok", "count": 0, "papers": []})

    return json.dumps({
        "status": "ok",
        "count": len(papers),
        "papers": [
            {
                "paper_id": p["paper_id"],
                "title": p["title"][:100],
                "authors": p.get("authors") or [],
                "arxiv_id": p.get("arxiv_id"),
                "indexed_at": p["indexed_at"],
                "year": paper_details.get(p["paper_id"], {}).get("year"),
                "venue": paper_details.get(p["paper_id"], {}).get("venue"),
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
        return json.dumps({
            "status": "error",
            "error_code": "paper_not_found",
            "message": f"Paper not found: {paper_id}",
        })

    return json.dumps({"status": "ok", **overview}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# delete_paper
# ---------------------------------------------------------------------------

async def delete_paper(paper_id: str) -> str:
    """Delete a paper and all its chunks."""
    from mapce.core.incremental import delete_paper_safe
    from mapce.db import get_connection, get_meta, init_index_meta

    db = get_connection()
    meta = get_meta(init_index_meta(db), paper_id)
    if meta is None or meta.get("status") == "deleted":
        return json.dumps({
            "status": "error",
            "error_code": "paper_not_found",
            "message": f"Paper not found: {paper_id}",
        })

    summary = delete_paper_safe(paper_id, db=db)
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
    from mapce.core.vector_index import index_report
    from mapce.db import get_connection, init_chunks, init_index_meta
    from mapce.db.operations import list_all_meta

    db = get_connection()
    chunks_table = init_chunks(db)
    meta_table = init_index_meta(db)

    papers = list_all_meta(
        meta_table,
        columns=["paper_id", "code_indexed", "code_status", "status"],
    )
    total_chunks = chunks_table.count_rows() if chunks_table else 0
    paper_chunks = chunks_table.count_rows("source_type = 'paper'") if chunks_table else 0
    code_chunks = chunks_table.count_rows("source_type = 'code'") if chunks_table else 0
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
        "paper_chunks": paper_chunks,
        "code_chunks": code_chunks,
        "vector_index": index_report(chunks_table),
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Agent paper reading
# ---------------------------------------------------------------------------

async def resolve_paper(identifier: str) -> str:
    """Resolve an internal paper ID or arXiv reference without network access."""
    from mapce.application.papers import resolve_paper as _resolve_paper

    return json.dumps(_resolve_paper(identifier), ensure_ascii=False)


async def read_paper_section(
    paper_id: str,
    section_path: str | None = None,
    chunk_id: str | None = None,
    include_subsections: bool = False,
    limit: int = 10,
    cursor: str | None = None,
) -> str:
    """Read stable, paginated paper content without embedding columns."""
    from mapce.application.papers import read_paper_section as _read_paper_section

    return json.dumps(
        _read_paper_section(
            paper_id,
            section_path=section_path,
            chunk_id=chunk_id,
            include_subsections=include_subsections,
            limit=limit,
            cursor=cursor,
        ),
        ensure_ascii=False,
    )


async def search_paper_content(
    paper_id: str,
    query: str,
    top_k: int = 10,
) -> str:
    """Search multiple relevant chunks inside one paper."""
    from mapce.application.papers import search_paper_content as _search_paper_content

    return json.dumps(
        _search_paper_content(paper_id, query, top_k=top_k),
        ensure_ascii=False,
    )


async def review_code_repository(paper_id: str, repo_url: str, action: str) -> str:
    """Apply a TUI repository review action through the shared write queue."""
    from mapce.application.repositories import review_code_repository as _review

    return json.dumps(_review(paper_id, repo_url, action), ensure_ascii=False)


async def delete_code_repository(paper_id: str, repo_url: str) -> str:
    """Delete one repository index through the shared write queue."""
    from mapce.application.repositories import delete_code_repository as _delete

    return json.dumps(_delete(paper_id, repo_url), ensure_ascii=False)
