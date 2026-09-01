#!/usr/bin/env python3
"""Create a fail-closed MAPCE research workspace."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path


DIRECTORIES = ("search", "papers", "evidence", "notes", "design", "manuscript", "cache", "build")
CSV_FILES = {
    "papers/candidates.csv": [
        "candidate_id", "title", "authors", "year", "doi", "arxiv_id", "url",
        "discovery_source", "query", "relevance_reason", "local_status", "oa_status",
        "index_source", "decision", "decision_reason",
    ],
    "papers/screening.csv": [
        "candidate_id", "stage", "decision", "reason", "reviewer", "reviewed_at",
    ],
    "evidence/evidence_ledger.csv": [
        "evidence_id", "paper_id", "chunk_id", "section_path", "claim_summary",
        "support_type", "verification_status", "notes",
    ],
    "evidence/claims.csv": [
        "claim_id", "claim_hash", "claim_type", "evidence_ids", "status", "notes",
    ],
}


def initialize_workspace(
    output_dir: Path,
    *,
    title: str,
    question: str,
    review_mode: str,
) -> Path:
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Research workspace is not empty: {output_dir}")
    if review_mode not in {"rapid", "prisma"}:
        raise ValueError("review_mode must be 'rapid' or 'prisma'")

    output_dir.mkdir(parents=True, exist_ok=True)
    for directory in DIRECTORIES:
        (output_dir / directory).mkdir()
    now = datetime.now(timezone.utc).isoformat()
    project = {
        "schema_version": 1,
        "title": title,
        "research_question": question,
        "review_mode": review_mode,
        "stage": "scoped",
        "created_at": now,
        "updated_at": now,
        "search_cutoff": None,
        "unresolved_decisions": [],
    }
    (output_dir / "project.json").write_text(
        json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "search/search_log.jsonl").touch()
    for relative, fields in CSV_FILES.items():
        with (output_dir / relative).open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerow(fields)
    (output_dir / "evidence/source_manifest.json").write_text(
        json.dumps({"schema_version": 1, "sources": []}, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "manuscript/review.md").write_text(
        "# DRAFT — NOT FOR SUBMISSION\n\n", encoding="utf-8"
    )
    (output_dir / "manuscript/review.tex").write_text(
        "% DRAFT — NOT FOR SUBMISSION\n", encoding="utf-8"
    )
    (output_dir / "manuscript/references.bib").touch()
    (output_dir / ".gitignore").write_text("cache/\nbuild/\n", encoding="utf-8")
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--review-mode", choices=("rapid", "prisma"), default="rapid")
    args = parser.parse_args()
    path = initialize_workspace(
        args.output_dir,
        title=args.title,
        question=args.question,
        review_mode=args.review_mode,
    )
    print(json.dumps({"status": "ok", "workspace": str(path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
