#!/usr/bin/env python3
"""Repair historical paper titles, authors, and paper chunk counts.

The command is dry-run by default. Pass ``--apply`` to mutate LanceDB.
It never reparses PDFs or recomputes unaffected paper/code embeddings.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import lancedb
import pyarrow as pa
import pyarrow.ipc as ipc
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mapce.core.chunking.paper import chunk_paper  # noqa: E402
from mapce.core.indexing import (  # noqa: E402
    _first_markdown_title,
    _is_placeholder_title,
)
from mapce.db import (  # noqa: E402
    ensure_index_meta_metadata_columns,
    sql_in_list,
    sql_str,
)
from mapce.db.connection import _get_data_dir  # noqa: E402

SPECIAL_TYPES = {"figure", "table"}


def _normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _find_markdown(papers_dir: Path, paper_id: str) -> Path | None:
    paper_dir = papers_dir / paper_id
    direct = paper_dir / f"{paper_id}.md"
    if direct.exists():
        return direct
    files = sorted(paper_dir.rglob("*.md")) if paper_dir.exists() else []
    return files[0] if files else None


def _read_local_title(papers_dir: Path, paper_id: str) -> str | None:
    markdown = _find_markdown(papers_dir, paper_id)
    if markdown is None:
        return None
    try:
        return _first_markdown_title(markdown.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None


def _load_cached_metadata(paths: list[Path] | None) -> dict[str, dict[str, Any]]:
    resolved: dict[str, dict[str, Any]] = {}
    for path in paths or []:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if "resolved_metadata" in payload:
            payload = payload["resolved_metadata"]
        if isinstance(payload, list):
            resolved.update({row["paper_id"]: row for row in payload})
        else:
            resolved.update(dict(payload))
    return resolved


def _paper_payload(paper: Any, source: str) -> dict[str, Any]:
    return {
        "title": paper.title,
        "authors": list(paper.authors),
        "matched_arxiv_id": paper.arxiv_id,
        "source": source,
    }


def resolve_metadata(
    meta_rows: list[dict[str, Any]],
    papers_dir: Path,
    *,
    cached: dict[str, dict[str, Any]],
    offline: bool,
) -> dict[str, dict[str, Any]]:
    """Resolve authoritative metadata without writing to the database."""
    resolved = dict(cached)
    if offline:
        return resolved

    from mapce.sources.arxiv import get_arxiv_metadata_batch, search_arxiv

    id_rows = [
        row for row in meta_rows
        if row["paper_id"] not in resolved and (row.get("arxiv_id") or "").strip()
    ]
    arxiv_ids = [str(row["arxiv_id"]).strip() for row in id_rows]
    fetched = get_arxiv_metadata_batch(arxiv_ids)
    for row in id_rows:
        normalized_id = re.sub(r"v\d+$", "", str(row["arxiv_id"]).strip())
        paper = fetched.get(normalized_id)
        if paper and paper.authors:
            resolved[row["paper_id"]] = _paper_payload(paper, "arxiv_id")

    no_id_rows = [
        row for row in meta_rows
        if row["paper_id"] not in resolved and not (row.get("arxiv_id") or "").strip()
    ]
    for index, row in enumerate(no_id_rows):
        if index:
            time.sleep(3.0)
        local_title = _read_local_title(papers_dir, row["paper_id"])
        title = local_title or row.get("title") or ""
        if not title:
            continue
        escaped = title.replace('"', " ")
        candidates = search_arxiv(f'ti:"{escaped}"', max_results=5)
        target = _normalize_title(title)
        matches = sorted(
            (
                (SequenceMatcher(None, target, _normalize_title(p.title)).ratio(), p)
                for p in candidates
                if p.authors
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        if matches and matches[0][0] >= 0.96:
            resolved[row["paper_id"]] = _paper_payload(matches[0][1], "arxiv_title")
    return resolved


def _metadata_for_chunking(
    meta: dict[str, Any],
    resolved: dict[str, Any] | None,
    title: str,
) -> dict[str, Any]:
    return {
        "title": title,
        "authors": list((resolved or {}).get("authors") or []),
        "year": None,
        "venue": "",
        "arxiv_id": meta.get("arxiv_id"),
        "doi": meta.get("doi"),
        "keywords": [],
    }


def build_plan(
    db: Any,
    data_dir: Path,
    resolved: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    meta_rows = db.open_table("index_meta").search().to_list()
    chunks = db.open_table("chunks").search().select([
        "paper_id", "source_type", "chunk_type", "title", "authors"
    ]).to_list()
    by_paper: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in chunks:
        by_paper[row.get("paper_id") or ""].append(row)

    papers_dir = data_dir / "papers"
    title_fixes = []
    author_fixes = []
    unresolved_authors = []
    special_repairs = []

    for meta in meta_rows:
        paper_id = meta["paper_id"]
        paper_rows = [r for r in by_paper[paper_id] if r.get("source_type") == "paper"]
        l1 = next((r for r in paper_rows if r.get("chunk_type") == "paper_l1"), {})
        external = resolved.get(paper_id)
        current_title = (meta.get("title") or "").strip()
        local_title = _read_local_title(papers_dir, paper_id)
        target_title = current_title
        if _is_placeholder_title(current_title, paper_id, meta.get("arxiv_id")):
            target_title = ((external or {}).get("title") or local_title or "").strip()
            if target_title and not _is_placeholder_title(
                target_title, paper_id, meta.get("arxiv_id")
            ):
                title_fixes.append({
                    "paper_id": paper_id,
                    "old_title": current_title,
                    "new_title": target_title,
                    "source": (external or {}).get("source") or "local_markdown",
                })

        target_authors = list((external or {}).get("authors") or [])
        current_authors = list(l1.get("authors") or [])
        meta_authors = list(meta.get("authors") or []) if "authors" in meta else []
        if target_authors:
            if current_authors != target_authors or meta_authors != target_authors:
                author_fixes.append({
                    "paper_id": paper_id,
                    "old_authors": current_authors,
                    "new_authors": target_authors,
                    "source": external.get("source"),
                    "matched_arxiv_id": external.get("matched_arxiv_id"),
                })
        elif not current_authors:
            unresolved_authors.append({
                "paper_id": paper_id,
                "title": target_title or current_title or local_title,
                "arxiv_id": meta.get("arxiv_id"),
            })

        current_paper_count = len(paper_rows)
        stored_count = int(meta.get("chunk_count") or 0)
        if current_paper_count != stored_count:
            markdown = _find_markdown(papers_dir, paper_id)
            if markdown is None:
                special_repairs.append({
                    "paper_id": paper_id,
                    "error": "local_markdown_missing",
                    "stored_count": stored_count,
                    "current_paper_count": current_paper_count,
                })
                continue
            metadata = _metadata_for_chunking(
                meta,
                external,
                target_title or current_title,
            )
            generated = chunk_paper(markdown.parent, metadata)
            generated_special = [c for c in generated if c["chunk_type"] in SPECIAL_TYPES]
            generated_body = [c for c in generated if c["chunk_type"] not in SPECIAL_TYPES]
            current_special = [r for r in paper_rows if r.get("chunk_type") in SPECIAL_TYPES]
            body_count = current_paper_count - len(current_special)
            if body_count != len(generated_body):
                special_repairs.append({
                    "paper_id": paper_id,
                    "error": "paper_body_count_mismatch",
                    "stored_count": stored_count,
                    "current_paper_count": current_paper_count,
                    "current_body_count": body_count,
                    "target_body_count": len(generated_body),
                })
                continue
            special_repairs.append({
                "paper_id": paper_id,
                "stored_count": stored_count,
                "current_paper_count": current_paper_count,
                "current_special_count": len(current_special),
                "target_special_count": len(generated_special),
                "target_paper_count": body_count + len(generated_special),
            })

    unresolved_titles = [
        row["paper_id"]
        for row in meta_rows
        if _is_placeholder_title(row.get("title"), row["paper_id"], row.get("arxiv_id"))
        and row["paper_id"] not in {fix["paper_id"] for fix in title_fixes}
    ]
    paper_chunk_count = sum(
        1 for row in chunks if row.get("source_type") == "paper"
    )
    code_chunk_count = sum(
        1 for row in chunks if row.get("source_type") == "code"
    )
    return {
        "mode": "dry-run",
        "data_dir": str(data_dir),
        "paper_count": len(meta_rows),
        "paper_chunk_count": paper_chunk_count,
        "code_chunk_count": code_chunk_count,
        "title_fixes": title_fixes,
        "author_fixes": author_fixes,
        "unresolved_titles": unresolved_titles,
        "unresolved_authors": unresolved_authors,
        "special_chunk_repairs": special_repairs,
        "resolved_metadata": resolved,
    }


def _backup(db: Any, data_dir: Path, plan: dict[str, Any]) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_dir = data_dir / "backups" / f"paper-metadata-{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    (backup_dir / "repair_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    meta_table = db.open_table("index_meta")
    chunks_table = db.open_table("chunks")
    pq.write_table(meta_table.search().to_arrow(), backup_dir / "index_meta.parquet")
    pq.write_table(
        chunks_table.search().where("source_type = 'paper'").select([
            "chunk_id", "paper_id", "title", "authors"
        ]).to_arrow(),
        backup_dir / "paper_chunk_metadata.parquet",
    )

    title_ids = [row["paper_id"] for row in plan["title_fixes"]]
    special_ids = [
        row["paper_id"] for row in plan["special_chunk_repairs"] if not row.get("error")
    ]
    affected_ids = sorted(set(title_ids + special_ids))
    if affected_ids:
        condition = (
            f"paper_id IN ({sql_in_list(affected_ids)}) AND "
            "(chunk_type = 'paper_l1' OR chunk_type IN ('figure', 'table'))"
        )
        affected = chunks_table.search().where(condition).to_arrow()
        with pa.OSFile(str(backup_dir / "reembedded_chunks.arrow"), "wb") as sink:
            with ipc.new_file(sink, affected.schema) as writer:
                writer.write_table(affected)
    versions = {
        "index_meta": meta_table.version,
        "chunks": chunks_table.version,
    }
    (backup_dir / "versions.json").write_text(
        json.dumps(versions, indent=2), encoding="utf-8"
    )
    return backup_dir


def _replace_l1_title(content: str, new_title: str) -> str:
    lines = content.splitlines()
    if lines and re.match(r"^\s*#(?!#)\s+", lines[0]):
        lines[0] = f"# {new_title}"
        return "\n".join(lines)
    return f"# {new_title}\n\n{content.lstrip()}"


def _regenerate_special_chunks(
    data_dir: Path,
    meta: dict[str, Any],
    external: dict[str, Any] | None,
    title: str,
) -> list[dict[str, Any]]:
    markdown = _find_markdown(data_dir / "papers", meta["paper_id"])
    if markdown is None:
        raise RuntimeError(f"Missing local Markdown for {meta['paper_id']}")
    generated = chunk_paper(
        markdown.parent,
        _metadata_for_chunking(meta, external, title),
    )
    return [row for row in generated if row["chunk_type"] in SPECIAL_TYPES]


def apply_plan(db: Any, data_dir: Path, plan: dict[str, Any]) -> Path:
    blockers = []
    if plan["unresolved_titles"]:
        blockers.append(f"unresolved titles: {len(plan['unresolved_titles'])}")
    if plan["unresolved_authors"]:
        blockers.append(f"unresolved authors: {len(plan['unresolved_authors'])}")
    bad_special = [row for row in plan["special_chunk_repairs"] if row.get("error")]
    if bad_special:
        blockers.append(f"unrepairable special chunks: {len(bad_special)}")
    if blockers:
        raise RuntimeError("Refusing to apply with " + "; ".join(blockers))

    backup_dir = _backup(db, data_dir, plan)
    meta_table = ensure_index_meta_metadata_columns(db.open_table("index_meta"))
    chunks_table = db.open_table("chunks")
    meta_rows = {row["paper_id"]: row for row in meta_table.search().to_list()}
    resolved = plan["resolved_metadata"]
    title_by_id = {
        row["paper_id"]: row["new_title"] for row in plan["title_fixes"]
    }

    from mapce.core.embedding import embed

    title_fixes = plan["title_fixes"]
    title_vectors = embed([row["new_title"] for row in title_fixes]) if title_fixes else []
    title_vector_by_id = {
        row["paper_id"]: vector for row, vector in zip(title_fixes, title_vectors)
    }

    l1_updates: dict[str, dict[str, Any]] = {}
    for row in title_fixes:
        paper_id = row["paper_id"]
        l1_rows = chunks_table.search().where(
            f"paper_id = {sql_str(paper_id)} AND chunk_type = 'paper_l1'"
        ).limit(1).to_list()
        if not l1_rows:
            raise RuntimeError(f"Missing L1 chunk for {paper_id}")
        l1 = l1_rows[0]
        content = _replace_l1_title(l1.get("content") or "", row["new_title"])
        l1_updates[paper_id] = {"content": content}
    l1_vectors = embed([
        l1_updates[row["paper_id"]]["content"] for row in title_fixes
    ]) if title_fixes else []
    for row, vector in zip(title_fixes, l1_vectors):
        l1_updates[row["paper_id"]]["embedding"] = vector

    special_by_id: dict[str, list[dict[str, Any]]] = {}
    all_special: list[dict[str, Any]] = []
    for repair in plan["special_chunk_repairs"]:
        paper_id = repair["paper_id"]
        meta = meta_rows[paper_id]
        title = title_by_id.get(paper_id, meta.get("title") or paper_id)
        rows = _regenerate_special_chunks(
            data_dir, meta, resolved.get(paper_id), title
        )
        special_by_id[paper_id] = rows
        all_special.extend(rows)
    special_vectors = embed([row["content"] for row in all_special]) if all_special else []
    for row, vector in zip(all_special, special_vectors):
        row["embedding"] = vector
        row["fulltext_search"] = row["content"]

    author_fix_ids = {
        row["paper_id"] for row in plan["author_fixes"]
    } - set(title_by_id)
    for paper_id in sorted(author_fix_ids):
        authors = list(resolved[paper_id]["authors"])
        chunks_table.update(
            where=f"paper_id = {sql_str(paper_id)} AND source_type = 'paper'",
            values={"authors": authors},
        )

    for row in title_fixes:
        paper_id = row["paper_id"]
        authors = list(resolved[paper_id]["authors"])
        chunks_table.update(
            where=f"paper_id = {sql_str(paper_id)} AND source_type = 'paper'",
            values={"title": row["new_title"], "authors": authors},
        )
        update = l1_updates[paper_id]
        chunks_table.update(
            where=f"paper_id = {sql_str(paper_id)} AND chunk_type = 'paper_l1'",
            values={
                "content": update["content"],
                "fulltext_search": update["content"],
                "embedding": update["embedding"],
            },
        )

    for paper_id, rows in special_by_id.items():
        condition = (
            f"paper_id = {sql_str(paper_id)} AND source_type = 'paper' "
            "AND chunk_type IN ('figure', 'table')"
        )
        (
            chunks_table.merge_insert("chunk_id")
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .when_not_matched_by_source_delete(condition)
            .execute(rows)
        )

    final_counts = Counter(
        row["paper_id"]
        for row in chunks_table.search().where("source_type = 'paper'").select([
            "paper_id"
        ]).to_list()
    )
    updated_meta = []
    for paper_id, meta in meta_rows.items():
        external = resolved.get(paper_id) or {}
        meta["authors"] = list(external.get("authors") or meta.get("authors") or [])
        if paper_id in title_by_id:
            meta["title"] = title_by_id[paper_id]
            meta["title_embedding"] = title_vector_by_id[paper_id]
        meta["chunk_count"] = int(final_counts.get(paper_id, 0))
        updated_meta.append(meta)
    (
        meta_table.merge_insert("paper_id")
        .when_matched_update_all()
        .when_not_matched_insert_all()
        .execute(updated_meta)
    )

    from mapce.core.vector_index import refresh_vector_indices

    refresh_vector_indices(chunks_table)
    return backup_dir


def rollback_backup(db: Any, backup_dir: Path) -> dict[str, Any]:
    """Restore all values changed by a prior apply operation."""
    plan_path = backup_dir / "repair_plan.json"
    if not plan_path.exists():
        raise RuntimeError(f"Invalid backup directory: {backup_dir}")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    meta_backup = pq.read_table(backup_dir / "index_meta.parquet").to_pylist()
    chunk_metadata = pq.read_table(
        backup_dir / "paper_chunk_metadata.parquet"
    ).to_pylist()

    meta_table = ensure_index_meta_metadata_columns(db.open_table("index_meta"))
    chunks_table = db.open_table("chunks")
    old_authors: dict[str, list[str]] = {}
    old_titles: dict[str, str] = {}
    for row in chunk_metadata:
        paper_id = row["paper_id"]
        old_authors.setdefault(paper_id, list(row.get("authors") or []))
        if row.get("title") is not None:
            old_titles.setdefault(paper_id, row["title"])
    for row in meta_backup:
        row["authors"] = old_authors.get(row["paper_id"], [])
    (
        meta_table.merge_insert("paper_id")
        .when_matched_update_all()
        .when_not_matched_insert_all()
        .execute(meta_backup)
    )

    for paper_id in sorted(old_authors):
        where = f"paper_id = {sql_str(paper_id)} AND source_type = 'paper'"
        if old_authors[paper_id]:
            chunks_table.update(
                where=where,
                values={
                    "authors": old_authors[paper_id],
                    "title": old_titles.get(paper_id),
                },
            )
        else:
            chunks_table.update(
                where=where,
                values={"title": old_titles.get(paper_id)},
            )
            chunks_table.update(
                where=where,
                values_sql={
                    "authors": "array_slice(make_array(CAST(NULL AS STRING)), 1, 0)"
                },
            )

    reembedded_path = backup_dir / "reembedded_chunks.arrow"
    if reembedded_path.exists():
        with pa.memory_map(str(reembedded_path), "r") as source:
            reembedded = ipc.open_file(source).read_all().to_pylist()
        old_l1 = [row for row in reembedded if row["chunk_type"] == "paper_l1"]
        if old_l1:
            (
                chunks_table.merge_insert("chunk_id")
                .when_matched_update_all()
                .when_not_matched_insert_all()
                .execute(old_l1)
            )
        special_ids = {
            row["paper_id"]
            for row in plan["special_chunk_repairs"]
            if not row.get("error")
        }
        for paper_id in sorted(special_ids):
            rows = [
                row for row in reembedded
                if row["paper_id"] == paper_id and row["chunk_type"] in SPECIAL_TYPES
            ]
            condition = (
                f"paper_id = {sql_str(paper_id)} AND source_type = 'paper' "
                "AND chunk_type IN ('figure', 'table')"
            )
            builder = (
                chunks_table.merge_insert("chunk_id")
                .when_matched_update_all()
                .when_not_matched_insert_all()
                .when_not_matched_by_source_delete(condition)
            )
            if rows:
                builder.execute(rows)
            else:
                chunks_table.delete(condition)

    from mapce.core.vector_index import refresh_vector_indices

    refresh_vector_indices(chunks_table)
    return {
        "mode": "rolled-back",
        "backup_dir": str(backup_dir),
        "paper_count": len(meta_backup),
        "title_rows_restored": len(plan["title_fixes"]),
        "author_rows_restored": len(plan["author_fixes"]),
        "special_chunk_sets_restored": len(plan["special_chunk_repairs"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback", type=Path)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--metadata-file", type=Path, action="append")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    data_dir = (args.data_dir or _get_data_dir()).expanduser().resolve()
    if not data_dir.exists():
        parser.error(f"Database directory does not exist: {data_dir}")
    db = lancedb.connect(str(data_dir))
    table_names = set(db.list_tables().tables)
    if not {"index_meta", "chunks"}.issubset(table_names):
        parser.error("Database must contain index_meta and chunks tables")

    if args.apply and args.rollback:
        parser.error("--apply and --rollback are mutually exclusive")
    if args.rollback:
        result = rollback_backup(db, args.rollback.expanduser().resolve())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    meta_rows = db.open_table("index_meta").search().to_list()
    cached = _load_cached_metadata(args.metadata_file)
    resolved = resolve_metadata(
        meta_rows,
        data_dir / "papers",
        cached=cached,
        offline=args.offline,
    )
    plan = build_plan(db, data_dir, resolved)
    if args.apply:
        backup_dir = apply_plan(db, data_dir, plan)
        plan["mode"] = "applied"
        plan["backup_dir"] = str(backup_dir)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    output = plan
    if args.quiet:
        output = {
            "mode": plan["mode"],
            "paper_count": plan["paper_count"],
            "title_fixes": len(plan["title_fixes"]),
            "author_fixes": len(plan["author_fixes"]),
            "unresolved_titles": len(plan["unresolved_titles"]),
            "unresolved_authors": len(plan["unresolved_authors"]),
            "special_chunk_repairs": len(plan["special_chunk_repairs"]),
            "backup_dir": plan.get("backup_dir"),
        }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
