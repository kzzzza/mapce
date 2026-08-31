"""Indexing orchestrator.

Ties together MinerU parsing → chunking → embedding → LanceDB writes
into a single end-to-end pipeline for indexing a paper.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from mapce.core.chunking.paper import chunk_paper
from mapce.core.embedding import embed, embed_single
from mapce.mineru.api import batch_parse
from mapce.db import (
    ensure_index_meta_code_columns,
    ensure_index_meta_metadata_columns,
    get_connection,
    init_chunks,
    init_index_meta,
    insert_chunks,
    sql_str,
    upsert_meta,
)


_ARXIV_ID_RE = re.compile(r"^(?:arxiv[:\s_-]*)?\d{4}\.\d{4,5}(?:v\d+)?$", re.IGNORECASE)


def _is_placeholder_title(title: str | None, *identifiers: str | None) -> bool:
    """Return whether a title is empty or merely repeats a storage identifier."""
    normalized = (title or "").strip()
    if not normalized or normalized.lower() in {"untitled", "unknown"}:
        return True
    if _ARXIV_ID_RE.fullmatch(normalized):
        return True
    folded = normalized.casefold()
    return any(
        folded == (value or "").strip().casefold()
        for value in identifiers
        if value
    )


def _first_markdown_title(markdown: str) -> str | None:
    """Find the first H1 title even when images or notices precede it."""
    for line in markdown.splitlines():
        match = re.match(r"^\s*#(?!#)\s+(.+?)\s*$", line)
        if match:
            candidate = match.group(1).strip()
            if candidate:
                return candidate
    return None


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
        title = _first_markdown_title(md) or ""
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


def _enrich_metadata_from_arxiv(metadata: dict[str, Any]) -> dict[str, Any]:
    """Best-effort enrichment, including the arXiv comment used for discovery."""
    arxiv_id = metadata.get("arxiv_id")
    if not arxiv_id or metadata.get("arxiv_comment"):
        return metadata
    try:
        from mapce.sources.arxiv import get_arxiv_metadata
        arxiv_meta = get_arxiv_metadata(str(arxiv_id))
    except Exception:
        return metadata
    if arxiv_meta is None:
        return metadata
    enriched = dict(metadata)
    if _is_placeholder_title(enriched.get("title"), str(arxiv_id)):
        enriched["title"] = arxiv_meta.title or enriched.get("title")
    if not enriched.get("authors"):
        enriched["authors"] = arxiv_meta.authors
    if not enriched.get("year") and arxiv_meta.published:
        enriched["year"] = int(arxiv_meta.published[:4])
    enriched["arxiv_comment"] = arxiv_meta.comment
    return enriched


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
    from mapce.service.runtime import assert_database_write_allowed

    assert_database_write_allowed()
    # Preliminary paper_id (from the pdf stem) used for the cache dir name and
    # to detect whether the final paper_id changed. Defined on both branches so
    # the comparison below never hits an unbound name.
    prelim_id = pdf_path.stem
    if output_dir is None:
        # Use persistent cache so images/tables survive across sessions
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
    metadata = _enrich_metadata_from_arxiv(metadata)

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
    from mapce.service.runtime import assert_database_write_allowed

    assert_database_write_allowed()
    db = get_connection()
    chunks_table = init_chunks(db)
    meta_table = init_index_meta(db)
    ensure_index_meta_code_columns(meta_table)
    ensure_index_meta_metadata_columns(meta_table)

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

    # Embed the title itself (not embeddings[0], which is the L1 content chunk).
    # check_duplicate compares an incoming title's embedding against this, so it
    # must be a title→title comparison to be meaningful.
    title = metadata.get("title", "Untitled")
    title_embedding = embed_single(title) if title else None

    upsert_meta(meta_table, {
        "paper_id": paper_id,
        "title": title,
        "authors": metadata.get("authors") or [],
        "arxiv_id": metadata.get("arxiv_id"),
        "doi": metadata.get("doi"),
        "title_embedding": title_embedding,
        "indexed_at": datetime.now(timezone.utc).isoformat(),
        "parser_version": "mineru_v4",
        "chunk_count": len(chunks),
        "has_code": False,
        "code_repo_url": None,
        "code_indexed": False,
        "code_status": "not_checked",
        "code_checked_at": None,
        "status": "complete",
        "error_msg": None,
    })

    # Repository discovery runs only after paper chunks and metadata have been
    # committed. Code failures therefore cannot roll back a readable paper.
    from mapce.core.code_indexing import CodeIndexingError, index_code_repository
    from mapce.core.code_repositories import (
        discover_code_repositories,
        save_discovered_repositories,
    )
    from mapce.mineru.parser import MinerUOutput

    markdown_available = True
    try:
        markdown = MinerUOutput(paper_dir).read_markdown()
    except Exception:
        markdown_available = False
        markdown = ""
    candidates = discover_code_repositories(
        markdown,
        title,
        str(metadata.get("arxiv_comment") or ""),
    )
    if markdown_available or candidates:
        save_discovered_repositories(paper_id, candidates, db=db)

    if on_progress:
        on_progress("code_discovery", {
            "paper_id": paper_id,
            "repositories": candidates,
        })

    for candidate in candidates:
        if candidate["confidence"] != "high":
            continue
        if on_progress:
            on_progress("code_indexing", {
                "paper_id": paper_id,
                "repo_url": candidate["repo_url"],
                "status": "indexing",
            })
        try:
            index_code_repository(
                candidate["repo_url"],
                paper_id,
                source=candidate["source"],
                confidence=candidate["confidence"],
                score=candidate["score"],
                evidence=candidate.get("evidence"),
                db=db,
            )
        except CodeIndexingError as exc:
            if on_progress:
                on_progress("code_indexing", {
                    "paper_id": paper_id,
                    "repo_url": candidate["repo_url"],
                    "status": "failed",
                    "error": str(exc),
                })

    if on_progress:
        on_progress("done", {"paper_id": paper_id, "chunk_count": len(chunks)})

    return paper_id


def _update_paper_paths(paper_id: str, old_dir: Path, new_dir: Path) -> None:
    """Update figure_path and table_image in DB after moving MinerU output."""
    try:
        from mapce.db import get_connection, init_chunks
        table = init_chunks(get_connection())
        rows = table.search().where(f"paper_id = {sql_str(paper_id)}").to_list()
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
                table.delete(f"chunk_id = {sql_str(r['chunk_id'])}")
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
    from mapce.service.runtime import assert_database_write_allowed

    assert_database_write_allowed()
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

    # Extract metadata from arXiv. Only new-style ids (YYMM.NNNNN)
    # encode the year; old-style ids (e.g. "hep-th/9901001") don't, so leave
    # year=None there and let the MinerU-derived metadata fill it in later.
    _ym = re.match(r"(\d{2})(\d{2})\.", arxiv_id)
    metadata = {
        "title": arxiv_id,  # will be updated from MinerU output
        "authors": [],
        "year": int("20" + _ym.group(1)) if _ym else None,
        "venue": "arXiv",
        "arxiv_id": arxiv_id,
        "doi": None,
        "keywords": [],
        "arxiv_comment": "",
    }
    metadata = _enrich_metadata_from_arxiv(metadata)
    # Try to get a better title from the markdown
    try:
        mineru = MinerUOutput(paper_dir)
        md = mineru.read_markdown()
        local_title = _first_markdown_title(md)
        if _is_placeholder_title(metadata.get("title"), arxiv_id) and local_title:
            metadata["title"] = local_title
    except Exception:
        pass

    # Index from already-parsed MinerU output (no re-upload)
    return _index_from_mineru_dir(paper_dir, metadata, on_progress=on_progress)


def index_paper_from_url(
    url: str,
    language: str = "en",
    on_progress: Callable[[str, dict], None] | None = None,
) -> str:
    """Parse and index a paper from a public HTTP(S) PDF URL."""
    from mapce.service.runtime import assert_database_write_allowed

    assert_database_write_allowed()
    from mapce.mineru.api import download_and_unpack, parse_from_url

    if on_progress:
        on_progress("mineru", {"status": "submitting_url", "url": url})
    result = parse_from_url(url, language=language)
    if result["state"] == "failed":
        raise RuntimeError(f"MinerU URL parsing failed for {url}: {result.get('err_msg')}")

    parsed = urlparse(url)
    filename = unquote(Path(parsed.path).name) or "remote-paper.pdf"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(filename).stem).strip("-._")
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    data_id = f"{stem or 'remote-paper'}-{digest}"
    cache_parent = _get_paper_cache_dir(data_id).parent
    paper_dir = download_and_unpack(
        {"data_id": data_id, "full_zip_url": result["full_zip_url"]},
        cache_parent,
    )
    metadata = _extract_metadata_from_mineru(paper_dir, Path(filename))
    return _index_from_mineru_dir(paper_dir, metadata, on_progress=on_progress)
