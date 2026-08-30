"""One-time cleanup: remove duplicate chunk_ids from the chunks table.

Code chunk_ids are deterministic (code:<paper>:<repo>:<type>:<idx>). Re-indexing
a repo before the dedup guard was added inserted a second identical copy of every
chunk, producing duplicate chunk_ids. This script removes the extra copies.

Strategy (no re-embedding, no re-cloning): for each repo_name that has any
duplicate chunk_id, read all its rows, keep one row per chunk_id (with its stored
embedding), delete the repo's chunks, and re-insert the unique set.

Usage:
    python scripts/dedup_code_chunks.py            # dry-run: report only
    python scripts/dedup_code_chunks.py --apply     # execute the cleanup

Tip: back up first with  cp -r ~/.mapce/data ~/.mapce/data.bak
(LanceDB also keeps prior versions until compaction, so this is recoverable.)
"""

import sys
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
_dotenv = Path(__file__).resolve().parents[1] / ".env"
if _dotenv.exists():
    load_dotenv(_dotenv)


def main(apply: bool) -> None:
    from mapce.db import get_connection, init_chunks
    from mapce.db.operations import delete_chunks_by_repo_name, insert_chunks
    from mapce.service.runtime import assert_database_write_allowed

    if apply:
        assert_database_write_allowed()

    db = get_connection()
    table = init_chunks(db)

    total_before = table.count_rows()
    arrow = table.to_arrow()
    chunk_id = arrow.column("chunk_id").to_pylist()
    repo_name = arrow.column("repo_name").to_pylist()

    # Global duplicate chunk_ids
    id_counts = Counter(chunk_id)
    dup_ids = {cid for cid, n in id_counts.items() if n > 1}

    if not dup_ids:
        print(f"No duplicate chunk_ids found. Total rows: {total_before}. Nothing to do.")
        return

    # Which repos are affected and by how much
    dup_rows_per_repo: dict[str, int] = defaultdict(int)
    for cid, repo in zip(chunk_id, repo_name):
        if cid in dup_ids and repo:
            dup_rows_per_repo[repo] += 1

    extra_rows = sum(n - 1 for n in id_counts.values() if n > 1)
    print("=== Duplicate chunk_id report ===")
    print(f"Total rows:            {total_before}")
    print(f"Distinct duplicate ids:{len(dup_ids)}")
    print(f"Extra (removable) rows:{extra_rows}")
    print(f"Affected repos:        {len(dup_rows_per_repo)}")
    for repo, n in sorted(dup_rows_per_repo.items(), key=lambda x: -x[1]):
        print(f"  - {repo}: {n} rows carrying duplicate ids")

    if not apply:
        print("\n[dry-run] No changes made. Re-run with --apply to execute.")
        return

    print("\n[apply] Rewriting affected repos with de-duplicated chunks…")
    rewritten = 0
    for repo in dup_rows_per_repo:
        rows = table.search().where(f"repo_name = '{repo}'").limit(10_000_000).to_list()
        unique: dict[str, dict] = {}
        for r in rows:
            r.pop("_distance", None)  # not a schema column
            unique.setdefault(r["chunk_id"], r)
        kept = list(unique.values())
        delete_chunks_by_repo_name(table, repo)
        insert_chunks(table, kept)
        rewritten += len(kept)
        print(f"  - {repo}: {len(rows)} → {len(kept)} unique chunks")

    total_after = table.count_rows()
    print(f"\nDone. Rows: {total_before} → {total_after} (removed {total_before - total_after}).")
    print("Run  python scripts/dedup_code_chunks.py  again to confirm 0 duplicates.")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv[1:])
