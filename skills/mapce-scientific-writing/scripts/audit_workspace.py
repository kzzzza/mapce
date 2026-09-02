#!/usr/bin/env python3
"""Audit MAPCE research evidence and citation registries without network access."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


EVIDENCE_MARKER = re.compile(r"\[evidence:([^\]]+)\]")
MARKDOWN_CITE = re.compile(r"\[@([A-Za-z0-9_:.+\-/]+)\]")
LATEX_CITE = re.compile(r"\\cite\w*\{([^}]+)\}")
BIBTEX_KEY = re.compile(r"@\w+\s*\{\s*([^,\s]+)\s*,", re.I)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _duplicates(values: list[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def audit(workspace: Path) -> dict[str, Any]:
    workspace = workspace.expanduser().resolve()
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    ledger = _read_csv(workspace / "evidence/evidence_ledger.csv")
    claims = _read_csv(workspace / "evidence/claims.csv")
    source_path = workspace / "evidence/source_manifest.json"
    try:
        sources = json.loads(source_path.read_text(encoding="utf-8")).get("sources", [])
    except (OSError, json.JSONDecodeError, AttributeError):
        sources = []
        errors.append({"code": "invalid_source_manifest", "message": str(source_path)})

    evidence_ids = [row.get("evidence_id", "").strip() for row in ledger]
    for value in sorted(_duplicates([value for value in evidence_ids if value])):
        errors.append({"code": "duplicate_evidence_id", "message": value})
    known_evidence = {value for value in evidence_ids if value}
    for row_number, row in enumerate(ledger, start=2):
        for field in ("evidence_id", "paper_id", "chunk_id", "section_path"):
            if not row.get(field, "").strip():
                errors.append({
                    "code": "missing_evidence_locator",
                    "message": f"evidence_ledger.csv:{row_number}:{field}",
                })

    claim_ids = [row.get("claim_id", "").strip() for row in claims]
    for value in sorted(_duplicates([value for value in claim_ids if value])):
        errors.append({"code": "duplicate_claim_id", "message": value})
    for row_number, row in enumerate(claims, start=2):
        for evidence_id in re.split(r"[,;\s]+", row.get("evidence_ids", "").strip()):
            if evidence_id and evidence_id not in known_evidence:
                errors.append({
                    "code": "unknown_claim_evidence",
                    "message": f"claims.csv:{row_number}:{evidence_id}",
                })

    md_path = workspace / "manuscript/review.md"
    tex_path = workspace / "manuscript/review.tex"
    bib_path = workspace / "manuscript/references.bib"
    markdown = md_path.read_text(encoding="utf-8") if md_path.is_file() else ""
    latex = tex_path.read_text(encoding="utf-8") if tex_path.is_file() else ""
    bibtex = bib_path.read_text(encoding="utf-8") if bib_path.is_file() else ""

    for marker in EVIDENCE_MARKER.findall(markdown):
        for evidence_id in [value.strip() for value in marker.split(",")]:
            if evidence_id and evidence_id not in known_evidence:
                errors.append({"code": "unknown_manuscript_evidence", "message": evidence_id})

    bib_keys = set(BIBTEX_KEY.findall(bibtex))
    md_keys = set(MARKDOWN_CITE.findall(markdown))
    tex_keys = {
        key.strip()
        for group in LATEX_CITE.findall(latex)
        for key in group.split(",")
        if key.strip()
    }
    for key in sorted((md_keys | tex_keys) - bib_keys):
        errors.append({"code": "undefined_bibtex_key", "message": key})
    if md_keys != tex_keys:
        errors.append({
            "code": "citation_format_mismatch",
            "message": f"markdown_only={sorted(md_keys - tex_keys)}, latex_only={sorted(tex_keys - md_keys)}",
        })

    source_keys = {str(source.get("citation_key") or "") for source in sources}
    for key in sorted(bib_keys - source_keys):
        warnings.append({"code": "bibtex_key_not_in_source_manifest", "message": key})

    unverified = [
        str(source.get("source_id") or source.get("paper_id") or "unknown")
        for source in sources
        if source.get("verification_status") != "human_verified"
    ]
    has_draft = "DRAFT" in markdown[:200].upper() and "DRAFT" in latex[:200].upper()
    if unverified and not has_draft:
        errors.append({
            "code": "draft_banner_required",
            "message": ", ".join(unverified),
        })

    manuscript_dir = workspace / "manuscript"
    tex_documents = sorted(manuscript_dir.glob("*.tex")) if manuscript_dir.is_dir() else []
    pdfs = [
        tex.with_suffix(".pdf")
        for tex in tex_documents
        if tex.with_suffix(".pdf").is_file()
    ]
    layout_approved = 0
    for pdf in pdfs:
        tex = pdf.with_suffix(".tex")
        qa_path = pdf.with_suffix(".layout-qa.json")
        try:
            qa = json.loads(qa_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            errors.append({"code": "layout_qa_required", "message": str(qa_path)})
            continue
        if qa.get("status") != "layout_approved":
            errors.append({"code": "layout_not_approved", "message": str(qa_path)})
            continue
        if qa.get("source_sha256") != _sha256(tex):
            errors.append({"code": "layout_source_changed", "message": str(tex)})
            continue
        if qa.get("pdf_sha256") != _sha256(pdf):
            errors.append({"code": "layout_pdf_changed", "message": str(pdf)})
            continue
        layout_approved += 1

    return {
        "status": "ok" if not errors else "error",
        "workspace": str(workspace),
        "errors": errors,
        "warnings": warnings,
        "counts": {
            "sources": len(sources),
            "evidence": len(ledger),
            "claims": len(claims),
            "bibtex_keys": len(bib_keys),
            "pdfs": len(pdfs),
            "layout_approved_pdfs": layout_approved,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args()
    result = audit(args.workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "ok":
        sys.exit(1)


if __name__ == "__main__":
    main()
