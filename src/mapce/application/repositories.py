"""TUI-facing repository review and deletion operations."""

from __future__ import annotations

from typing import Any

import lancedb

from mapce.core.code_repositories import (
    get_repository_associations,
    normalize_github_url,
    sync_paper_code_state,
    utc_now,
)
from mapce.db import get_connection, get_meta, init_index_meta, sql_str
from mapce.db.operations import (
    delete_chunks_by_repo_url,
    delete_legacy_chunks_by_repo,
    upsert_code_repo,
)


def _paper_exists(db: lancedb.DBConnection, paper_id: str) -> bool:
    meta = get_meta(init_index_meta(db), paper_id)
    return bool(meta is not None and meta.get("status") != "deleted")


def review_code_repository(
    paper_id: str,
    repo_url: str,
    action: str,
    *,
    db: lancedb.DBConnection | None = None,
) -> dict[str, Any]:
    """Ignore a candidate or make one active repository primary."""
    from mapce.service.runtime import assert_database_write_allowed

    assert_database_write_allowed()
    if action not in {"ignore", "set_primary"}:
        return {
            "status": "error",
            "error_code": "invalid_repository_action",
            "message": f"Unsupported repository action: {action}",
        }
    normalized = normalize_github_url(repo_url)
    if normalized is None:
        return {
            "status": "error",
            "error_code": "invalid_repository_url",
            "message": "repo_url must be a GitHub owner/repo URL.",
        }
    db = db or get_connection()
    if not _paper_exists(db, paper_id):
        return {
            "status": "error",
            "error_code": "paper_not_found",
            "message": f"Paper not found: {paper_id}",
        }
    try:
        table = db.open_table("paper_code_repos")
    except Exception:
        return {
            "status": "error",
            "error_code": "repository_not_found",
            "message": f"Repository is not associated with paper {paper_id}: {normalized}",
        }
    rows = get_repository_associations(paper_id, db)
    target = next((row for row in rows if row.get("repo_url") == normalized), None)
    if target is None:
        return {
            "status": "error",
            "error_code": "repository_not_found",
            "message": f"Repository is not associated with paper {paper_id}: {normalized}",
        }
    if action == "ignore" and target.get("status") == "indexed":
        return {
            "status": "error",
            "error_code": "repository_already_indexed",
            "message": "Delete the indexed repository before ignoring its association.",
        }

    now = utc_now()
    if action == "ignore":
        target["status"] = "ignored"
        target["is_primary"] = False
        target["error_msg"] = None
        target["updated_at"] = now
        upsert_code_repo(table, target)
    else:
        if target.get("status") == "ignored":
            return {
                "status": "error",
                "error_code": "repository_ignored",
                "message": "An ignored repository cannot be primary.",
            }
        for row in rows:
            row["is_primary"] = row.get("repo_url") == normalized
            row["updated_at"] = now
            upsert_code_repo(table, row)
    meta = sync_paper_code_state(paper_id, db=db, checked=True)
    return {
        "status": "ok",
        "paper_id": paper_id,
        "repo_url": normalized,
        "action": action,
        "code_status": (meta or {}).get("code_status"),
        "repositories": get_repository_associations(paper_id, db),
    }


def delete_code_repository(
    paper_id: str,
    repo_url: str,
    *,
    db: lancedb.DBConnection | None = None,
) -> dict[str, Any]:
    """Delete one paper-owned code index and its repository association."""
    from mapce.service.runtime import assert_database_write_allowed

    assert_database_write_allowed()
    normalized = normalize_github_url(repo_url)
    if normalized is None:
        return {
            "status": "error",
            "error_code": "invalid_repository_url",
            "message": "repo_url must be a GitHub owner/repo URL.",
        }
    db = db or get_connection()
    if not _paper_exists(db, paper_id):
        return {
            "status": "error",
            "error_code": "paper_not_found",
            "message": f"Paper not found: {paper_id}",
        }
    rows = get_repository_associations(paper_id, db)
    target = next((row for row in rows if row.get("repo_url") == normalized), None)
    if target is None:
        return {
            "status": "error",
            "error_code": "repository_not_found",
            "message": f"Repository is not associated with paper {paper_id}: {normalized}",
        }
    chunks_deleted = 0
    mappings_deleted = 0
    if hasattr(db, "list_tables"):
        table_names = set(db.list_tables().tables)
    else:  # LanceDB < 0.24 compatibility
        table_names = set(db.table_names())
    if "chunks" in table_names:
        chunks = db.open_table("chunks")
        chunks_deleted += delete_chunks_by_repo_url(chunks, paper_id, normalized)
        chunks_deleted += delete_legacy_chunks_by_repo(
            chunks, paper_id, target.get("repo_name") or normalized.rsplit("/", 1)[-1]
        )
    if "paper_code_mapping" in table_names:
        mappings = db.open_table("paper_code_mapping")
        before = mappings.count_rows()
        mappings.delete(
            f"paper_id = {sql_str(paper_id)} AND repo_name = {sql_str(target.get('repo_name') or '')}"
        )
        mappings_deleted = before - mappings.count_rows()
    table = db.open_table("paper_code_repos")
    table.delete(f"association_id = {sql_str(target['association_id'])}")
    meta = sync_paper_code_state(paper_id, db=db, checked=True)
    return {
        "status": "ok",
        "paper_id": paper_id,
        "repo_url": normalized,
        "chunks_deleted": chunks_deleted,
        "mappings_deleted": mappings_deleted,
        "code_status": (meta or {}).get("code_status"),
        "repositories": get_repository_associations(paper_id, db),
    }
