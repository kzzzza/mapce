"""Async handler functions for MCP tools.

Each function takes keyword arguments matching the tool's inputSchema
and returns a JSON string.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path


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
    from mapce.core.retrieval import search_papers as _search_papers

    results, intent = _search_papers(
        query=query, top_k=top_k,
        year_min=year_min, year_max=year_max, venue=venue,
    )

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
) -> str:
    """Search indexed code chunks."""
    from mapce.core.retrieval import search_code as _search_code

    results, intent = _search_code(query=query, top_k=top_k)

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

    if source_type == "arxiv":
        paper_id = index_paper_from_arxiv(arxiv_id=source, language=language)
    elif source_type in ("local", "url"):
        pdf_path = Path(source).expanduser()
        if not pdf_path.exists():
            return json.dumps({"status": "error", "message": f"File not found: {source}"})
        paper_id = _index_paper(pdf_path=pdf_path, language=language)
    else:
        return json.dumps({"status": "error", "message": f"Unknown source_type: {source_type}"})

    return json.dumps({
        "status": "ok",
        "paper_id": paper_id,
        "message": f"Paper indexed: {paper_id}",
    })


# ---------------------------------------------------------------------------
# index_code
# ---------------------------------------------------------------------------

async def index_code(
    repo_url: str,
    paper_id: str,
) -> str:
    """Clone and index a code repository, linking it to a paper."""
    from mapce.core.chunking.code import chunk_repo
    from mapce.core.embedding import embed
    from mapce.db import get_connection, init_chunks, init_mapping, init_index_meta
    from mapce.db.operations import insert_chunks, upsert_meta, get_meta

    tmp_dir = Path(tempfile.mkdtemp(prefix="mapce_repo_"))
    repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
    repo_path = tmp_dir / repo_name

    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, str(repo_path)],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            return json.dumps({
                "status": "error",
                "message": f"Failed to clone: {result.stderr[-500:]}",
            })

        chunks = chunk_repo(paper_id, repo_url, repo_path)
        contents = [c["content"] for c in chunks]
        embeddings = embed(contents)
        for c, emb in zip(chunks, embeddings):
            c["embedding"] = emb
            c["fulltext_search"] = c["content"]

        db = get_connection()
        chunks_table = init_chunks(db)
        meta_table = init_index_meta(db)

        insert_chunks(chunks_table, chunks)

        meta = get_meta(meta_table, paper_id)
        if meta:
            meta["has_code"] = True
            meta["code_repo_url"] = repo_url
            meta["code_indexed"] = True
            meta["status"] = "complete"
            upsert_meta(meta_table, meta)

        return json.dumps({
            "status": "ok",
            "paper_id": paper_id,
            "repo_name": repo_name,
            "chunk_count": len(chunks),
            "message": f"Indexed {len(chunks)} chunks from {repo_name}.",
        })

    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


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

    return json.dumps({
        "status": "ok",
        "total_papers": len(papers),
        "papers_with_code": papers_with_code,
        "total_chunks": total_chunks,
    }, ensure_ascii=False)
