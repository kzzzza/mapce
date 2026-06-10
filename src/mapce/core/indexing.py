"""Indexing orchestrator.

Ties together MinerU parsing → chunking → embedding → LanceDB writes
into a single end-to-end pipeline for indexing a paper.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from mapce.core.chunking.paper import chunk_paper
from mapce.core.embedding import embed
from mapce.db import (
    get_connection,
    init_chunks,
    init_index_meta,
    insert_chunks,
    upsert_meta,
)
from mapce.mineru.api import batch_parse


def _get_paper_cache_dir(paper_id: str) -> Path:
    """Persistent directory for storing MinerU output for a paper.

    Uses MAPCE_DATA_DIR / 'papers' / paper_id so parsed results
    (images, tables, markdown) survive across sessions.
    """
    from mapce.db.connection import _get_data_dir
    d = _get_data_dir() / "papers" / paper_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _extract_arxiv_id_from_pdf(pdf_path: Path) -> str | None:
    """Attempt to extract arXiv ID from a PDF filename or path.

    Looks for patterns like 2301.12345 or arXiv:2301.12345.
    """
    import re

    name = pdf_path.stem
    # Match arXiv ID patterns
    m = re.search(r"(?:arxiv[:\-_]*)?(\d{4}\.\d{4,5})", name, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


def _extract_metadata_from_mineru(paper_dir: Path, pdf_path: Path) -> dict[str, Any]:
    """Extract basic metadata from MinerU output and filename.

    Returns a dict with: title, authors, year, venue, arxiv_id, doi, keywords.
    This is a best-effort extraction; metadata can be enriched later.
    """
    arxiv_id = _extract_arxiv_id_from_pdf(pdf_path)

    # Try to read title from the first heading of the markdown
    from mapce.mineru.parser import MinerUOutput
    mineru = MinerUOutput(paper_dir)
    title = ""
    try:
        md = mineru.read_markdown()
        lines = md.strip().split("\n")
        if lines and lines[0].startswith("#"):
            title = lines[0].lstrip("#").strip()
    except Exception:
        pass

    if not title:
        title = pdf_path.stem.replace("_", " ").replace("-", " ")

    return {
        "title": title,
        "authors": [],
        "year": None,
        "venue": "",
        "arxiv_id": arxiv_id,
        "doi": None,
        "keywords": [],
    }


def index_paper(
    pdf_path: Path,
    output_dir: Path | None = None,
    metadata: dict[str, Any] | None = None,
    language: str = "en",
    on_progress: Callable[[str, dict], None] | None = None,
) -> str:
    """Index a single paper PDF end-to-end.

    1. MinerU parse (if output_dir not already populated)
    2. Chunk into L1/L2/L3 + Figure/Table
    3. Compute embeddings for all chunks
    4. Write to LanceDB (chunks + index_meta)

    Args:
        pdf_path: Path to the PDF file.
        output_dir: Directory for MinerU output. Auto-created in a temp dir if None.
        metadata: Optional paper metadata override.
        language: "en" or "ch" for MinerU parsing.
        on_progress: Optional callback(stage, info) for progress reporting.

    Returns:
        The paper_id of the indexed paper.
    """
    if output_dir is None:
        # Use persistent cache so images/tables survive across sessions
        # We need a preliminary paper_id for the directory name — use pdf stem
        prelim_id = pdf_path.stem
        output_dir = _get_paper_cache_dir(prelim_id)
    else:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    if on_progress:
        on_progress("mineru", {"status": "parsing"})

    paper_dirs = batch_parse(
        file_paths=[pdf_path],
        output_dir=output_dir,
        language=language,
        enable_formula=True,
        enable_table=True,
    )

    if not paper_dirs:
        raise RuntimeError(f"MinerU parsing failed or returned no output for {pdf_path}")

    paper_dir = paper_dirs[0]

    if metadata is None:
        metadata = _extract_metadata_from_mineru(paper_dir, pdf_path)

    paper_id = _index_from_mineru_dir(paper_dir, metadata, on_progress=on_progress)

    # If the final paper_id differs from prelim_id, move to the correct directory
    if paper_id != prelim_id:
        target_dir = _get_paper_cache_dir(paper_id)
        if target_dir != paper_dir.parent:
            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
            shutil.move(str(paper_dir.parent), str(target_dir))
            # Update figure/table paths in DB to reflect new location
            _update_paper_paths(paper_id, paper_dir.parent, target_dir)

    return paper_id


def _index_from_mineru_dir(
    paper_dir: Path,
    metadata: dict[str, Any],
    on_progress: Callable[[str, dict], None] | None = None,
) -> str:
    """Index an already-parsed MinerU output directory.

    Shared by index_paper (local PDF via batch_parse) and
    index_paper_from_arxiv (URL-based via parse_from_url).
    """
    db = get_connection()
    chunks_table = init_chunks(db)
    meta_table = init_index_meta(db)

    if on_progress:
        on_progress("chunking", {"status": "chunking"})

    chunks = chunk_paper(paper_dir, metadata)
    paper_id = chunks[0]["paper_id"] if chunks else metadata.get("title", "unknown")

    if on_progress:
        on_progress("chunking", {"status": "chunking", "chunk_count": len(chunks)})

    if on_progress:
        on_progress("embedding", {"status": "embedding", "chunk_count": len(chunks)})

    contents = [c["content"] for c in chunks]
    embeddings = embed(contents)

    for c, emb in zip(chunks, embeddings):
        c["embedding"] = emb
        c["fulltext_search"] = c["content"]

    if on_progress:
        on_progress("db_write", {"status": "writing"})

    insert_chunks(chunks_table, chunks)

    upsert_meta(meta_table, {
        "paper_id": paper_id,
        "title": metadata.get("title", "Untitled"),
        "arxiv_id": metadata.get("arxiv_id"),
        "doi": metadata.get("doi"),
        "title_embedding": embeddings[0] if embeddings else None,
        "indexed_at": datetime.now(timezone.utc).isoformat(),
        "parser_version": "mineru_v4",
        "chunk_count": len(chunks),
        "has_code": False,
        "code_repo_url": None,
        "code_indexed": False,
        "status": "code_pending" if _detect_github_url(paper_dir) else "complete",
        "error_msg": None,
    })

    if on_progress:
        on_progress("done", {"paper_id": paper_id, "chunk_count": len(chunks)})

    return paper_id


def _detect_github_url(paper_dir: Path) -> bool:
    """Check if the paper mentions a GitHub URL in its markdown."""
    import re
    from mapce.mineru.parser import MinerUOutput

    try:
        mineru = MinerUOutput(paper_dir)
        md = mineru.read_markdown()
        return bool(re.search(r"github\.com/[\w.-]+/[\w.-]+", md))
    except Exception:
        return False


def _update_paper_paths(paper_id: str, old_dir: Path, new_dir: Path) -> None:
    """Update figure_path and table_image in DB after moving MinerU output."""
    try:
        from mapce.db import get_connection, init_chunks
        table = init_chunks(get_connection())
        rows = table.search().where(f"paper_id = '{paper_id}'").to_list()
        updated = []
        old_s = str(old_dir)
        new_s = str(new_dir)
        for r in rows:
            changed = False
            for field in ("figure_path", "table_image"):
                val = r.get(field)
                if val and isinstance(val, str) and val.startswith(old_s):
                    r[field] = val.replace(old_s, new_s, 1)
                    changed = True
            if changed:
                updated.append(r)
        # LanceDB doesn't support in-place updates — delete and re-add
        if updated:
            for r in updated:
                table.delete(f"chunk_id = '{r['chunk_id']}'")
            table.add(updated)
    except Exception:
        pass  # best-effort; the data is still available at the new path


def index_batch(
    pdf_paths: list[Path],
    output_dir: Path | None = None,
    language: str = "en",
    on_progress: Callable[[str, dict], None] | None = None,
) -> list[dict[str, Any]]:
    """Index a batch of paper PDFs.

    Returns a list of {"pdf": str, "paper_id": str, "status": "ok"|"failed", "error": str|None}.
    """
    results = []
    for pdf_path in pdf_paths:
        try:
            paper_id = index_paper(
                pdf_path=pdf_path,
                output_dir=output_dir / pdf_path.stem if output_dir else None,
                language=language,
                on_progress=on_progress,
            )
            results.append({"pdf": str(pdf_path), "paper_id": paper_id, "status": "ok", "error": None})
        except Exception as e:
            results.append({"pdf": str(pdf_path), "paper_id": None, "status": "failed", "error": str(e)})
    return results


def index_paper_from_arxiv(
    arxiv_id: str,
    language: str = "en",
    on_progress: Callable[[str, dict], None] | None = None,
) -> str:
    """Download a paper from arXiv, parse with MinerU, and index it.

    Uses MinerU's URL-based extraction endpoint to handle the PDF fetch.

    Args:
        arxiv_id: arXiv paper ID (e.g., "2301.12345").
        language: Paper language for OCR.
        on_progress: Optional progress callback.

    Returns:
        The paper_id of the indexed paper.
    """
    from mapce.mineru.api import parse_from_url
    from mapce.mineru.parser import MinerUOutput

    url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

    if on_progress:
        on_progress("mineru", {"status": "submitting_url", "arxiv_id": arxiv_id})

    result = parse_from_url(url, language=language)
    if result["state"] == "failed":
        raise RuntimeError(f"MinerU URL parsing failed for arXiv:{arxiv_id}: {result.get('err_msg')}")

    # Download and unpack to persistent cache so images/tables survive.
    # download_and_unpack creates output_dir / data_id, so pass the parent
    # to get ~/.mapce/data/papers/<arxiv_id>/ (not .../<arxiv_id>/<arxiv_id>/).
    from mapce.mineru.api import download_and_unpack

    cache_parent = _get_paper_cache_dir(arxiv_id).parent
    paper_dir = download_and_unpack(
        {"data_id": arxiv_id, "full_zip_url": result["full_zip_url"]},
        cache_parent,
    )

    # Extract metadata from arxiv (basic)
    metadata = {
        "title": arxiv_id,  # will be updated from MinerU output
        "authors": [],
        "year": int(f"20{arxiv_id[:2]}") if len(arxiv_id) >= 4 else None,
        "venue": "arXiv",
        "arxiv_id": arxiv_id,
        "doi": None,
        "keywords": [],
    }
    # Try to get a better title from the markdown
    try:
        mineru = MinerUOutput(paper_dir)
        md = mineru.read_markdown()
        lines = md.strip().split("\n")
        if lines and lines[0].startswith("#"):
            metadata["title"] = lines[0].lstrip("#").strip()
    except Exception:
        pass

    # Index from already-parsed MinerU output (no re-upload)
    return _index_from_mineru_dir(paper_dir, metadata, on_progress=on_progress)
