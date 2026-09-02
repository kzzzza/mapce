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


def test_latex_log_gate_rejects_large_overfull_and_unresolved_references():
    module = _load(
        "skills/mapce-scientific-writing/scripts/latex_quality_gate.py",
        "mapce_latex_log_gate",
    )
    result = module.parse_latex_log(
        "Overfull \\hbox (1.5pt too wide)\n"
        "Overfull \\hbox (309.64569pt too wide)\n"
        "LaTeX Warning: There were undefined references.\n",
        overfull_tolerance_pt=2.0,
    )

    assert result["status"] == "failed"
    assert [item["amount_pt"] for item in result["overfull_failures"]] == [309.64569]
    assert result["unresolved_references"]


def test_latex_visual_reasons_track_layout_and_page_changes():
    module = _load(
        "skills/mapce-scientific-writing/scripts/latex_quality_gate.py",
        "mapce_latex_visual_reasons",
    )
    first_signature, has_layout = module.layout_signature(
        "Text\\begin{table}A\\end{table}"
    )
    changed_signature, _ = module.layout_signature(
        "Different prose\\begin{table}B\\end{table}"
    )

    assert has_layout is True
    assert first_signature != changed_signature
    assert module.visual_reasons(
        final=False,
        force_visual=False,
        page_count=4,
        table_figure_signature=first_signature,
        has_layout_content=True,
        last_approved=None,
    ) == ["new_tables_or_figures"]
    reasons = module.visual_reasons(
        final=True,
        force_visual=False,
        page_count=5,
        table_figure_signature=changed_signature,
        has_layout_content=True,
        last_approved={"page_count": 4, "table_figure_signature": first_signature},
    )
    assert reasons == ["final_delivery", "tables_or_figures_changed", "page_count_changed"]
    removed = module.visual_reasons(
        final=False,
        force_visual=False,
        page_count=4,
        table_figure_signature=module.layout_signature("plain text")[0],
        has_layout_content=False,
        last_approved={"page_count": 4, "table_figure_signature": first_signature},
    )
    assert removed == ["tables_or_figures_changed"]


def test_latex_layout_signature_detects_referenced_image_changes(tmp_path):
    module = _load(
        "skills/mapce-scientific-writing/scripts/latex_quality_gate.py",
        "mapce_latex_image_signature",
    )
    figures = tmp_path / "figures"
    figures.mkdir()
    image = figures / "figure.png"
    image.write_bytes(b"first-image")
    source = "\\graphicspath{{figures/}}\\includegraphics{figure}"
    first, has_layout = module.layout_signature(source, base_dir=tmp_path)
    image.write_bytes(b"changed-image")
    changed, _ = module.layout_signature(source, base_dir=tmp_path)

    assert has_layout is True
    assert first != changed


def test_latex_visual_pass_publishes_pdf_and_hash_bound_qa(tmp_path):
    module = _load(
        "skills/mapce-scientific-writing/scripts/latex_quality_gate.py",
        "mapce_latex_visual_pass",
    )
    workspace = tmp_path / "research"
    tex = workspace / "manuscript/review.tex"
    tex.parent.mkdir(parents=True)
    tex.write_text("\\documentclass{article}\\begin{document}ok\\end{document}")
    paths = module._document_paths(workspace, tex)
    candidate = paths["compile_dir"] / "review.pdf"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"candidate-pdf")
    rendered = paths["pages_dir"] / "page-0001.png"
    rendered.parent.mkdir(parents=True)
    rendered.write_bytes(b"rendered-page")
    module._write_json(paths["report"], {
        "status": "visual_pending",
        "source_sha256": module.sha256_file(tex),
        "page_count": 1,
        "table_figure_signature": "signature",
        "compile": {"candidate_pdf": str(candidate)},
        "log_check": {"overfull_tolerance_pt": 2.0},
        "visual_review": {"status": "pending", "attempt": 1, "pages": [str(rendered)]},
    })

    result = module.record_visual_review(
        workspace,
        tex,
        result="pass",
        reviewed_pages="all",
        notes="inspected",
    )
    qa = json.loads(paths["qa_record"].read_text())

    assert result["status"] == "layout_approved"
    assert paths["output_pdf"].read_bytes() == b"candidate-pdf"
    assert qa["status"] == "layout_approved"
    assert qa["source_sha256"] == module.sha256_file(tex)
    assert qa["pdf_sha256"] == module.sha256_file(paths["output_pdf"])


def test_latex_visual_failure_requires_issue_and_caps_automatic_rechecks(tmp_path):
    module = _load(
        "skills/mapce-scientific-writing/scripts/latex_quality_gate.py",
        "mapce_latex_visual_failure",
    )
    workspace = tmp_path / "research"
    tex = workspace / "manuscript/review.tex"
    tex.parent.mkdir(parents=True)
    tex.write_text("\\documentclass{article}")
    paths = module._document_paths(workspace, tex)
    candidate = paths["compile_dir"] / "review.pdf"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"candidate")
    rendered = paths["pages_dir"] / "page-0001.png"
    rendered.parent.mkdir(parents=True)
    rendered.write_bytes(b"rendered-page")

    module._write_json(paths["report"], {
        "status": "visual_pending",
        "page_count": 1,
        "table_figure_signature": "sig",
        "compile": {"candidate_pdf": str(candidate)},
        "log_check": {"overfull_tolerance_pt": 2.0},
        "visual_review": {"attempt": 1, "pages": [str(rendered)]},
    })
    with pytest.raises(ValueError, match="at least one issue"):
        module.record_visual_review(
            workspace, tex, result="fail", reviewed_pages="all"
        )

    for attempt in range(1, 4):
        module._write_json(paths["report"], {
            "status": "visual_pending",
            "page_count": 1,
            "table_figure_signature": "sig",
            "compile": {"candidate_pdf": str(candidate)},
            "log_check": {"overfull_tolerance_pt": 2.0},
            "visual_review": {"attempt": attempt, "pages": [str(rendered)]},
        })
        result = module.record_visual_review(
            workspace,
            tex,
            result="fail",
            reviewed_pages="all",
            issues=["overlap"],
        )
    state = json.loads(paths["state"].read_text())
    assert result["visual_review"]["automatic_repair_rounds_remaining"] == 0
    assert state["visual_failures"] == 3


def test_latex_visual_pass_rejects_unresolved_issues(tmp_path):
    module = _load(
        "skills/mapce-scientific-writing/scripts/latex_quality_gate.py",
        "mapce_latex_visual_unresolved",
    )
    workspace = tmp_path / "research"
    tex = workspace / "manuscript/review.tex"
    tex.parent.mkdir(parents=True)
    tex.write_text("\\documentclass{article}")
    paths = module._document_paths(workspace, tex)
    candidate = paths["compile_dir"] / "review.pdf"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"candidate")
    rendered = paths["pages_dir"] / "page-0001.png"
    rendered.parent.mkdir(parents=True)
    rendered.write_bytes(b"rendered")
    module._write_json(paths["report"], {
        "status": "visual_pending",
        "page_count": 1,
        "table_figure_signature": "sig",
        "compile": {"candidate_pdf": str(candidate)},
        "log_check": {"overfull_tolerance_pt": 2.0},
        "visual_review": {"attempt": 1, "pages": [str(rendered)]},
    })

    with pytest.raises(ValueError, match="cannot retain unresolved"):
        module.record_visual_review(
            workspace,
            tex,
            result="pass",
            reviewed_pages="all",
            issues=["table overlap"],
        )


def test_evidence_audit_requires_current_layout_qa_for_published_pdf(tmp_path):
    audit_module = _load(
        "skills/mapce-scientific-writing/scripts/audit_workspace.py",
        "mapce_audit_layout_qa",
    )
    workspace = _make_workspace(tmp_path)
    tex = workspace / "manuscript/review.tex"
    pdf = workspace / "manuscript/review.pdf"
    qa = workspace / "manuscript/review.layout-qa.json"
    pdf.write_bytes(b"pdf")

    missing = audit_module.audit(workspace)
    assert "layout_qa_required" in {error["code"] for error in missing["errors"]}

    qa.write_text(json.dumps({
        "status": "layout_approved",
        "source_sha256": audit_module._sha256(tex),
        "pdf_sha256": audit_module._sha256(pdf),
    }))
    accepted = audit_module.audit(workspace)

    assert accepted["status"] == "ok"
    assert accepted["counts"]["layout_approved_pdfs"] == 1

    tex.write_text(tex.read_text() + "\n% changed after approval\n")
    stale = audit_module.audit(workspace)
    assert "layout_source_changed" in {error["code"] for error in stale["errors"]}
