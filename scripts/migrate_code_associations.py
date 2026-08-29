#!/usr/bin/env python3
"""Migrate legacy paper/code state to paper_code_repos.

The default mode is a read-only dry-run. Pass --apply to back up metadata
tables and write the migration. Paper and code embeddings are never rebuilt.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import lancedb
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
load_dotenv(ROOT / ".env")

from mapce.core.code_repositories import (  # noqa: E402
    discover_code_repositories,
    make_association_row,
    save_discovered_repositories,
    sync_paper_code_state,
)
from mapce.db.connection import _get_data_dir  # noqa: E402
from mapce.db.operations import (  # noqa: E402
    ensure_index_meta_code_columns,
    get_code_repo,
    get_meta,
    init_code_repos,
    init_index_meta,
    list_all_meta,
    upsert_code_repo,
    upsert_meta,
)


def _read_markdown(papers_dir: Path, paper_id: str) -> str | None:
    direct = papers_dir / paper_id
    candidates = list(direct.rglob("*.md")) if direct.exists() else []
    if not candidates and papers_dir.exists():
        candidates = [
            path for path in papers_dir.rglob("*.md")
            if paper_id in path.parts or paper_id in path.name
        ]
    if not candidates:
        return None
    path = max(candidates, key=lambda item: item.stat().st_size)
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def classify(meta_rows: list[dict], papers_dir: Path) -> tuple[list[dict], Counter]:
    plans: list[dict] = []
    counts: Counter = Counter()
    for meta in meta_rows:
        paper_id = meta["paper_id"]
        if meta.get("code_indexed") and meta.get("code_repo_url"):
            item = {
                "paper_id": paper_id,
                "classification": "indexed",
                "repositories": [{
                    "repo_url": meta["code_repo_url"],
                    "repo_name": meta["code_repo_url"].rstrip("/").rsplit("/", 1)[-1].removesuffix(".git"),
                    "source": "legacy",
                    "confidence": "high",
                    "score": 9,
                    "evidence": "Migrated from index_meta.code_repo_url",
                    "is_primary": True,
                    "status": "indexed",
                }],
            }
        else:
            markdown = _read_markdown(papers_dir, paper_id)
            if markdown is None:
                item = {
                    "paper_id": paper_id,
                    "classification": "not_checked",
                    "repositories": [],
                    "reason": "local_markdown_missing",
                }
            else:
                repositories = discover_code_repositories(markdown, meta.get("title") or "")
                if any(repo["confidence"] == "high" for repo in repositories):
                    classification = "pending"
                elif repositories:
                    classification = "needs_review"
                else:
                    classification = "no_code"
                item = {
                    "paper_id": paper_id,
                    "classification": classification,
                    "repositories": repositories,
                }
        if meta.get("status") == "code_pending":
            item["paper_status_change"] = "code_pending -> complete"
            counts["paper_status_changes"] += 1
        counts[item["classification"]] += 1
        counts["repository_associations"] += len(item["repositories"])
        plans.append(item)
    return plans, counts


def _backup_tables(data_dir: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_dir = data_dir / "backups" / f"code-associations-{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    for table_name in ("index_meta", "paper_code_mapping", "paper_code_repos"):
        source = data_dir / f"{table_name}.lance"
        if source.exists():
            shutil.copytree(source, backup_dir / source.name)
    return backup_dir


def apply_migration(db, data_dir: Path, plans: list[dict]) -> Path:
    backup_dir = _backup_tables(data_dir)
    meta_table = ensure_index_meta_code_columns(init_index_meta(db))
    repo_table = init_code_repos(db)

    for item in plans:
        paper_id = item["paper_id"]
        classification = item["classification"]
        if classification == "indexed":
            candidate = item["repositories"][0]
            existing = get_code_repo(repo_table, paper_id, candidate["repo_url"])
            row = make_association_row(
                paper_id,
                candidate["repo_url"],
                source="legacy",
                confidence="high",
                score=9,
                evidence=candidate["evidence"],
                is_primary=True,
                status="indexed",
                existing=existing,
            )
            if row["indexed_at"] is None:
                meta = get_meta(meta_table, paper_id) or {}
                row["indexed_at"] = (existing or {}).get("indexed_at") or meta.get("indexed_at")
            upsert_code_repo(repo_table, row)
            sync_paper_code_state(paper_id, db=db, checked=True)
        elif classification in {"pending", "needs_review", "no_code"}:
            save_discovered_repositories(paper_id, item["repositories"], db=db)
        else:
            meta = get_meta(meta_table, paper_id)
            if meta:
                meta["code_status"] = "not_checked"
                meta["code_checked_at"] = None
                if meta.get("status") == "code_pending":
                    meta["status"] = "complete"
                upsert_meta(meta_table, meta)
    return backup_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Back up metadata and apply migration")
    parser.add_argument("--data-dir", type=Path, help="Override MAPCE_DATA_DIR")
    parser.add_argument("--details", action="store_true", help="Include per-paper classifications")
    args = parser.parse_args()

    data_dir = (args.data_dir or _get_data_dir()).expanduser().resolve()
    if not data_dir.exists():
        parser.error(f"Database directory does not exist: {data_dir}")
    db = lancedb.connect(str(data_dir))
    try:
        table_names = db.list_tables().tables
    except AttributeError:
        table_names = db.table_names()
    if "index_meta" not in table_names:
        parser.error(f"index_meta table does not exist in: {data_dir}")

    meta_rows = list_all_meta(db.open_table("index_meta"))
    plans, counts = classify(meta_rows, data_dir / "papers")
    report = {
        "mode": "apply" if args.apply else "dry-run",
        "data_dir": str(data_dir),
        "paper_count": len(meta_rows),
        "classification_counts": dict(sorted(counts.items())),
        "rebuild_embeddings": False,
    }
    if args.apply:
        report["backup_dir"] = str(apply_migration(db, data_dir, plans))
    if args.details:
        report["papers"] = plans
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
