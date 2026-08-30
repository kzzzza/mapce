#!/usr/bin/env python3
"""Inspect or build MAPCE's LanceDB vector, scalar, and full-text indices.

Default mode is read-only. Pass ``--apply`` to create missing indices, or
``--apply --replace`` to rebuild them using the current configuration.
Embeddings and chunk content are never regenerated.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
load_dotenv(ROOT / ".env")

from mapce.core.vector_index import (  # noqa: E402
    create_vector_indices,
    index_report,
    refresh_vector_indices,
)
from mapce.db import get_connection  # noqa: E402


def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Create missing indices")
    parser.add_argument(
        "--replace", action="store_true", help="Rebuild existing indices (requires --apply)"
    )
    parser.add_argument(
        "--refresh", action="store_true", help="Index appended rows (requires --apply)"
    )
    parser.add_argument("--data-dir", type=Path, help="Override MAPCE_DATA_DIR")
    args = parser.parse_args()
    if (args.replace or args.refresh) and not args.apply:
        parser.error("--replace/--refresh require --apply")

    data_dir = (
        args.data_dir.expanduser().resolve()
        if args.data_dir
        else None
    )
    db = get_connection(data_dir)
    try:
        table = db.open_table("chunks")
    except Exception as exc:
        parser.error(f"chunks table does not exist: {exc}")

    database_path = data_dir or Path(db.uri.removeprefix("file://"))
    size_before = _directory_size(database_path)
    before = index_report(table)
    if not args.apply:
        result = {
            "mode": "dry-run",
            "before": before,
            "storage_bytes": size_before,
            "embeddings_rebuilt": False,
        }
    else:
        started = time.perf_counter()
        if args.refresh and not args.replace:
            create_vector_indices(table, replace=False)
            after = refresh_vector_indices(table)
        else:
            create_vector_indices(table, replace=args.replace)
            after = refresh_vector_indices(table)
        size_after = _directory_size(database_path)
        result = {
            "mode": "apply",
            "replace": args.replace,
            "refresh": args.refresh,
            "before": before,
            "after": after,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "storage_before_bytes": size_before,
            "storage_after_bytes": size_after,
            "storage_delta_bytes": size_after - size_before,
            "embeddings_rebuilt": False,
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
