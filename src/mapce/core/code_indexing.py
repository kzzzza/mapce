"""Shared code-repository indexing service used by automatic and MCP flows."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import lancedb

from mapce.core.chunking.code import chunk_repo
from mapce.core.code_repositories import (
    get_repository_associations,
    make_association_row,
    normalize_github_url,
    repository_identity,
    repository_name,
    sync_paper_code_state,
    utc_now,
)
from mapce.core.embedding import embed
from mapce.db import (
    delete_chunks_by_repo_url,
    delete_legacy_chunks_by_repo,
    ensure_index_meta_code_columns,
    get_code_repo,
    get_connection,
    get_meta,
    init_chunks,
    init_code_repos,
    insert_chunks,
    upsert_code_repo,
)


class PaperNotFoundError(LookupError):
    """Raised before repository or association work when a paper is absent."""


class InvalidRepositoryURLError(ValueError):
    """Raised for repository URLs outside the supported GitHub owner/repo form."""


class CodeIndexingError(RuntimeError):
    """Raised after a repository association has been marked failed."""


def _clone_repo(repo_url: str, destination: Path) -> None:
    result = subprocess.run(
        ["git", "clone", "--depth", "1", repo_url, str(destination)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git clone failed")[-1000:].strip()
        raise CodeIndexingError(detail)


def _prepare_chunks(
    paper_id: str,
    repo_url: str,
    repo_path: Path,
    repo_id: str,
    display_name: str,
) -> list[dict[str, Any]]:
    chunks = chunk_repo(paper_id, repo_url, repo_path)
    for chunk in chunks:
        chunk["repo_url"] = repo_url
        chunk["repo_name"] = display_name
        section_path = chunk.get("section_path")
        if isinstance(section_path, str) and section_path.startswith(repo_id):
            chunk["section_path"] = display_name + section_path[len(repo_id):]
        content = chunk.get("content")
        if isinstance(content, str):
            chunk["content"] = content.replace(
                f"# Repository: {repo_id}", f"# Repository: {display_name}", 1
            )
    return chunks


def index_code_repository(
    repo_url: str,
    paper_id: str,
    *,
    source: str = "user",
    confidence: str = "high",
    score: int = 9,
    evidence: str | None = None,
    db: lancedb.DBConnection | None = None,
) -> dict[str, Any]:
    """Clone, chunk, embed and idempotently replace one paper's repository.

    Paper existence is checked before association writes or network access.
    Paper chunks and paper indexing status are never rolled back on code errors.
    """
    from mapce.service.runtime import assert_database_write_allowed

    assert_database_write_allowed()
    if db is None:
        db = get_connection()

    # This is deliberately the first table operation. A missing paper must not
    # create paper_code_repos or start a clone.
    try:
        meta_table = db.open_table("index_meta")
    except Exception as exc:
        raise PaperNotFoundError(f"Paper not found: {paper_id}") from exc
    meta = get_meta(meta_table, paper_id)
    if meta is None or meta.get("status") == "deleted":
        raise PaperNotFoundError(f"Paper not found: {paper_id}")

    normalized = normalize_github_url(repo_url)
    if normalized is None:
        raise InvalidRepositoryURLError(
            "Repository URL must identify a GitHub owner/repo repository."
        )

    ensure_index_meta_code_columns(meta_table)
    repo_table = init_code_repos(db)
    existing = get_code_repo(repo_table, paper_id, normalized)
    current_rows = get_repository_associations(paper_id, db)
    if existing and existing.get("source") == "user" and source != "user":
        source = "user"
        confidence = "high"
        score = max(score, int(existing.get("score") or 0))
        evidence = existing.get("evidence") or evidence
    is_primary = source == "user" or (existing or {}).get(
        "is_primary", not any(r.get("is_primary") for r in current_rows)
    )
    if source == "user":
        for row in current_rows:
            if row.get("is_primary") and row.get("repo_url") != normalized:
                row["is_primary"] = False
                row["updated_at"] = utc_now()
                upsert_code_repo(repo_table, row)
        if evidence is None:
            evidence = "User-provided repository"
    repo_id = repository_identity(normalized)
    display_name = repository_name(normalized)

    association = make_association_row(
        paper_id,
        normalized,
        source=source,
        confidence=confidence,
        score=score,
        evidence=evidence if evidence is not None else (existing or {}).get("evidence"),
        is_primary=is_primary,
        status="indexing",
        existing=existing,
    )
    upsert_code_repo(repo_table, association)
    sync_paper_code_state(paper_id, db=db, checked=True)

    tmp_dir: Path | None = None
    try:
        tmp_dir = Path(tempfile.mkdtemp(prefix="mapce_repo_"))
        repo_path = tmp_dir / repo_id
        _clone_repo(normalized, repo_path)
        chunks = _prepare_chunks(paper_id, normalized, repo_path, repo_id, display_name)
        if not chunks:
            raise CodeIndexingError("Repository produced no indexable chunks.")

        embeddings = embed([chunk["content"] for chunk in chunks])
        if len(embeddings) != len(chunks):
            raise CodeIndexingError("Embedding count did not match code chunk count.")
        for chunk, embedding in zip(chunks, embeddings):
            chunk["embedding"] = embedding
            chunk["fulltext_search"] = chunk["content"]

        chunks_table = init_chunks(db)
        removed = delete_chunks_by_repo_url(chunks_table, paper_id, normalized)
        # Old code chunks populated repo_url only on some levels. Clean the
        # remaining URL-less rows during the first replacement.
        removed += delete_legacy_chunks_by_repo(chunks_table, paper_id, display_name)
        insert_chunks(chunks_table, chunks)

        association = make_association_row(
            paper_id,
            normalized,
            source=source,
            confidence=confidence,
            score=score,
            evidence=association.get("evidence"),
            is_primary=is_primary,
            status="indexed",
            existing=association,
        )
        association["indexed_at"] = utc_now()
        upsert_code_repo(repo_table, association)
        meta = sync_paper_code_state(paper_id, db=db, checked=True)
        return {
            "paper_id": paper_id,
            "repo_url": normalized,
            "repo_name": display_name,
            "chunk_count": len(chunks),
            "replaced_chunks": removed,
            "code_status": (meta or {}).get("code_status", "indexed"),
        }
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        failed = make_association_row(
            paper_id,
            normalized,
            source=source,
            confidence=confidence,
            score=score,
            evidence=association.get("evidence"),
            is_primary=is_primary,
            status="failed",
            existing=association,
            error_msg=message[:2000],
        )
        try:
            upsert_code_repo(repo_table, failed)
            sync_paper_code_state(paper_id, db=db, checked=True)
        except Exception:
            pass
        if isinstance(exc, CodeIndexingError):
            raise
        raise CodeIndexingError(message) from exc
    finally:
        if tmp_dir is not None:
            shutil.rmtree(tmp_dir, ignore_errors=True)
