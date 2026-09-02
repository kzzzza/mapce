from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load(relative: str, name: str) -> ModuleType:
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_workspace_initializer_creates_contract_and_refuses_overwrite(tmp_path):
    module = _load(
        "skills/mapce-research-workflow/scripts/init_workspace.py",
        "mapce_workspace_init",
    )
    workspace = tmp_path / "research" / "robot-control"

    created = module.initialize_workspace(
        workspace,
        title="Robot control",
        question="How do successor-state methods develop?",
        review_mode="rapid",
    )

    assert created == workspace.resolve()
    project = json.loads((workspace / "project.json").read_text())
    assert project["stage"] == "scoped"
    assert project["indexing_authorization"] == {
        "mode": "per_paper",
        "scope": "current_project",
        "explicit_user_authorization": False,
    }
    assert (workspace / "evidence/evidence_ledger.csv").is_file()
    assert "DRAFT" in (workspace / "manuscript/review.md").read_text()
    with pytest.raises(FileExistsError):
        module.initialize_workspace(
            workspace, title="Other", question="Other", review_mode="rapid"
        )


def test_workspace_initializer_requires_explicit_autonomous_indexing_permission(tmp_path):
    module = _load(
        "skills/mapce-research-workflow/scripts/init_workspace.py",
        "mapce_workspace_indexing_permission",
    )

    with pytest.raises(ValueError, match="explicit user authorization"):
        module.initialize_workspace(
            tmp_path / "rejected",
            title="Robot control",
            question="Question",
            review_mode="rapid",
            indexing_permission="autonomous",
        )

    workspace = module.initialize_workspace(
        tmp_path / "accepted",
        title="Robot control",
        question="Question",
        review_mode="rapid",
        indexing_permission="autonomous",
        user_authorized_autonomous_indexing=True,
    )
    project = json.loads((workspace / "project.json").read_text())
    assert project["indexing_authorization"] == {
        "mode": "autonomous",
        "scope": "current_project",
        "explicit_user_authorization": True,
    }


def test_discovery_parsers_and_identity_deduplication():
    module = _load(
        "skills/mapce-literature-discovery/scripts/discover_academic.py",
        "mapce_discovery",
    )
    atom = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry><id>http://arxiv.org/abs/2505.04961v2</id><updated>2025-05-08T00:00:00Z</updated>
      <published>2025-05-08T00:00:00Z</published><title>Successor State Method</title>
      <summary>A robot control method.</summary><author><name>A. Author</name></author></entry>
    </feed>"""
    openalex = {
        "results": [{
            "display_name": "Successor State Method",
            "publication_year": 2025,
            "ids": {"doi": "https://doi.org/10.1000/XYZ", "arxiv": "https://arxiv.org/abs/2505.04961"},
            "authorships": [{"author": {"display_name": "A. Author"}}],
            "open_access": {"is_oa": True},
            "best_oa_location": {"landing_page_url": "https://arxiv.org/abs/2505.04961", "pdf_url": "https://arxiv.org/pdf/2505.04961"},
        }]
    }

    arxiv_rows = module.search_arxiv("successor state", 10, fetcher=lambda _: atom)
    openalex_rows = module.search_openalex("successor state", 10, fetcher=lambda _: openalex)
    rows = module.deduplicate(openalex_rows + arxiv_rows)

    assert arxiv_rows[0].arxiv_id == "2505.04961"
    assert openalex_rows[0].doi == "10.1000/xyz"
    assert len(rows) == 1
    assert rows[0].discovery_source == "arxiv+openalex"
    assert rows[0].query == "successor state"
    assert rows[0].index_source


def test_discovery_deduplication_merges_transitive_ids_and_logs_errors(tmp_path):
    module = _load(
        "skills/mapce-literature-discovery/scripts/discover_academic.py",
        "mapce_discovery_transitive",
    )
    rows = module.deduplicate([
        module.Candidate(title="DOI record", year="2025", doi="10.1000/x", discovery_source="crossref", query="q1"),
        module.Candidate(title="arXiv record", year="2024", arxiv_id="2505.04961", discovery_source="arxiv", query="q2"),
        module.Candidate(title="Bridge", doi="10.1000/x", arxiv_id="2505.04961", discovery_source="openalex", query="q3"),
    ])
    log = tmp_path / "search/search_log.jsonl"
    module.append_search_log(
        log,
        query="successor state",
        sources=["arxiv", "openalex"],
        result_count=len(rows),
        errors=[{"source": "openalex", "error": "rate limited"}],
    )

    assert len(rows) == 1
    assert rows[0].discovery_source == "arxiv+crossref+openalex"
    record = json.loads(log.read_text(encoding="utf-8"))
    assert record["query"] == "successor state"
    assert record["errors"][0]["source"] == "openalex"


def _make_workspace(tmp_path: Path) -> Path:
    init = _load(
        "skills/mapce-research-workflow/scripts/init_workspace.py",
        "mapce_workspace_init_for_audit",
    )
    workspace = tmp_path / "research"
    init.initialize_workspace(
        workspace, title="Review", question="Question", review_mode="rapid"
    )
    return workspace


def test_evidence_audit_accepts_traceable_draft(tmp_path):
    audit_module = _load(
        "skills/mapce-scientific-writing/scripts/audit_workspace.py",
        "mapce_audit_valid",
    )
    workspace = _make_workspace(tmp_path)
    (workspace / "evidence/source_manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "sources": [{
            "source_id": "S001", "paper_id": "2505.04961", "citation_key": "author2025",
            "verification_status": "stored_metadata_only",
        }],
    }), encoding="utf-8")
    with (workspace / "evidence/evidence_ledger.csv").open("a", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerow([
            "E001", "2505.04961", "2505.04961:l3:1", "3 Method", "Method claim",
            "supports", "stored_metadata_only", "",
        ])
    with (workspace / "evidence/claims.csv").open("a", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerow(["C001", "hash", "factual", "E001", "draft", ""])
    (workspace / "manuscript/review.md").write_text(
        "# DRAFT — NOT FOR SUBMISSION\nClaim [evidence:E001] [@author2025]\n",
        encoding="utf-8",
    )
    (workspace / "manuscript/review.tex").write_text(
        "% DRAFT — NOT FOR SUBMISSION\nClaim \\cite{author2025}.\n", encoding="utf-8"
    )
    (workspace / "manuscript/references.bib").write_text(
        "@article{author2025, title={Verified title}}\n", encoding="utf-8"
    )

    result = audit_module.audit(workspace)

    assert result["status"] == "ok"
    assert result["errors"] == []


def test_evidence_audit_reports_missing_locator_and_undefined_references(tmp_path):
    audit_module = _load(
        "skills/mapce-scientific-writing/scripts/audit_workspace.py",
        "mapce_audit_invalid",
    )
    workspace = _make_workspace(tmp_path)
    with (workspace / "evidence/evidence_ledger.csv").open("a", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerow(["E001", "paper", "", "", "claim", "supports", "missing", ""])
    (workspace / "manuscript/review.md").write_text(
        "# DRAFT — NOT FOR SUBMISSION\nClaim [evidence:E999] [@missing].\n", encoding="utf-8"
    )

    result = audit_module.audit(workspace)
    codes = {error["code"] for error in result["errors"]}

    assert result["status"] == "error"
    assert "missing_evidence_locator" in codes
    assert "unknown_manuscript_evidence" in codes
    assert "undefined_bibtex_key" in codes
    assert "citation_format_mismatch" in codes
