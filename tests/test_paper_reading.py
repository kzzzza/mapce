from __future__ import annotations

from datetime import datetime, timezone

import lancedb
import pytest

from mapce.application import papers
from mapce.db.schema import CHUNKS_SCHEMA, INDEX_META_SCHEMA


def _row(schema, **values):
    row = {field.name: None for field in schema}
    row.update(values)
    return row


def _meta(paper_id, *, arxiv_id=None, title=None):
    return _row(
        INDEX_META_SCHEMA,
        paper_id=paper_id,
        title=title or paper_id,
        authors=["Ada Researcher"],
        arxiv_id=arxiv_id,
        indexed_at=datetime.now(timezone.utc).isoformat(),
        chunk_count=5,
        has_code=False,
        code_indexed=False,
        code_status="no_code",
        status="complete",
    )


def _chunk(
    chunk_id,
    paper_id,
    chunk_type,
    section_path,
    chunk_index,
    content,
    vector_value,
):
    vector = [0.0] * 1024
    vector[0] = vector_value
    return _row(
        CHUNKS_SCHEMA,
        chunk_id=chunk_id,
        chunk_type=chunk_type,
        source_type="paper",
        paper_id=paper_id,
        content=content,
        fulltext_search=content,
        embedding=vector,
        title=f"Title {paper_id}",
        authors=["Ada Researcher"],
        section_path=section_path,
        section_level=3 if chunk_type == "paper_l3" else 2,
        chunk_index=chunk_index,
    )


@pytest.fixture
def paper_db(tmp_path):
    db = lancedb.connect(tmp_path / "db")
    meta = db.create_table("index_meta", schema=INDEX_META_SCHEMA)
    meta.add(
        [
            _meta("paper-one", arxiv_id="2412.04368", title="Paper One"),
            _meta("legacy-paper", arxiv_id="hep-th/9901001", title="Legacy Paper"),
            _meta("paper-two", arxiv_id="2501.00001", title="Paper Two"),
        ]
    )
    chunks = db.create_table("chunks", schema=CHUNKS_SCHEMA)
    chunks.add(
        [
            _chunk("p1-l1", "paper-one", "paper_l1", "", 0, "abstract", 0.1),
            _chunk("p1-l2", "paper-one", "paper_l2", "1. Method", 0, "method section", 0.8),
            _chunk("p1-l3-a", "paper-one", "paper_l3", "1. Method", 1, "forward backward method", 1.0),
            _chunk("p1-l3-b", "paper-one", "paper_l3", "1. Method", 2, "training objective", 0.9),
            _chunk("p1-sub-l2", "paper-one", "paper_l2", "1. Method > 1.1 Training", 3, "training section", 0.7),
            _chunk("p1-sub-l3", "paper-one", "paper_l3", "1. Method > 1.1 Training", 4, "subsection details", 0.85),
            _chunk("p1-other", "paper-one", "paper_l3", "2. Experiments", 5, "benchmark results", 0.2),
            _chunk("p2-l3", "paper-two", "paper_l3", "1. Method", 1, "forward backward distractor", 1.0),
        ]
    )
    return db


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2412.04368", "2412.04368"),
        ("arXiv:2412.04368v2", "2412.04368"),
        ("https://arxiv.org/abs/2412.04368v3", "2412.04368"),
        ("https://arxiv.org/pdf/2412.04368.pdf?download=1", "2412.04368"),
        ("hep-th/9901001v4", "hep-th/9901001"),
    ],
)
def test_normalize_arxiv_id(value, expected):
    assert papers.normalize_arxiv_id(value) == expected


def test_resolve_paper_supports_internal_new_and_legacy_ids(paper_db, monkeypatch):
    monkeypatch.setattr(papers, "embed_single", lambda _: pytest.fail("embedding was loaded"))

    internal = papers.resolve_paper("paper-one", db=paper_db)
    versioned = papers.resolve_paper("arXiv:2412.04368v2", db=paper_db)
    legacy = papers.resolve_paper("https://arxiv.org/abs/hep-th/9901001", db=paper_db)

    assert internal["paper_id"] == "paper-one"
    assert versioned["paper_id"] == "paper-one"
    assert legacy["paper_id"] == "legacy-paper"


def test_resolve_paper_reports_invalid_and_missing_ids(paper_db):
    invalid = papers.resolve_paper("arXiv:24.123", db=paper_db)
    missing = papers.resolve_paper("2502.99999", db=paper_db)

    assert invalid["error_code"] == "invalid_arxiv_id"
    assert missing["error_code"] == "paper_not_indexed"


def test_read_section_paginates_l3_without_crossing_boundary(paper_db):
    first = papers.read_paper_section(
        "paper-one", section_path="1. Method", limit=1, db=paper_db
    )
    second = papers.read_paper_section(
        "paper-one",
        section_path="1. Method",
        limit=1,
        cursor=first["next_cursor"],
        db=paper_db,
    )

    ids = [first["chunks"][0]["chunk_id"], second["chunks"][0]["chunk_id"]]
    assert ids == ["p1-l3-a", "p1-l3-b"]
    assert first["total_chunks"] == 2
    assert "embedding" not in first["chunks"][0]
    assert all("Training" not in item["section_path"] for item in first["chunks"] + second["chunks"])


def test_read_section_can_include_subsections_and_validate_chunk_ownership(paper_db):
    expanded = papers.read_paper_section(
        "paper-one",
        chunk_id="p1-l2",
        include_subsections=True,
        limit=10,
        db=paper_db,
    )
    wrong_paper = papers.read_paper_section(
        "paper-one", chunk_id="p2-l3", db=paper_db
    )

    assert [item["chunk_id"] for item in expanded["chunks"]] == [
        "p1-l3-a",
        "p1-l3-b",
        "p1-sub-l3",
    ]
    assert wrong_paper["error_code"] == "chunk_not_found"


def test_read_section_rejects_cursor_from_different_selector(paper_db):
    first = papers.read_paper_section(
        "paper-one", section_path="1. Method", limit=1, db=paper_db
    )
    result = papers.read_paper_section(
        "paper-one",
        section_path="2. Experiments",
        cursor=first["next_cursor"],
        db=paper_db,
    )

    assert result["error_code"] == "invalid_cursor"


def test_read_section_invalidates_cursor_after_section_changes(paper_db):
    first = papers.read_paper_section(
        "paper-one", section_path="1. Method", limit=1, db=paper_db
    )
    paper_db.open_table("chunks").add(
        [_chunk("p1-l3-new", "paper-one", "paper_l3", "1. Method", 3, "new text", 0.5)]
    )

    result = papers.read_paper_section(
        "paper-one",
        section_path="1. Method",
        limit=1,
        cursor=first["next_cursor"],
        db=paper_db,
    )

    assert result["error_code"] == "invalid_cursor"


def test_search_paper_content_is_scoped_to_one_paper(paper_db, monkeypatch):
    query_vector = [0.0] * 1024
    query_vector[0] = 1.0
    monkeypatch.setattr(papers, "embed_single", lambda _: query_vector)

    result = papers.search_paper_content("paper-one", "forward backward", top_k=3, db=paper_db)

    assert result["status"] == "ok"
    assert result["count"] == 3
    assert all(item["chunk_id"] != "p2-l3" for item in result["results"])
    assert all("embedding" not in item for item in result["results"])
    assert all("dense_fine" in item["retrieval_sources"] for item in result["results"])


def test_search_paper_content_fails_safely_on_vector_error(paper_db, monkeypatch):
    monkeypatch.setattr(papers, "embed_single", lambda _: (_ for _ in ()).throw(RuntimeError("boom")))

    result = papers.search_paper_content("paper-one", "method", db=paper_db)

    assert result["error_code"] == "vector_search_failed"
    assert result["results"] == []


def test_missing_paper_returns_before_embedding(paper_db, monkeypatch):
    monkeypatch.setattr(papers, "embed_single", lambda _: pytest.fail("embedding was loaded"))

    result = papers.search_paper_content("missing", "method", db=paper_db)

    assert result["error_code"] == "paper_not_found"
