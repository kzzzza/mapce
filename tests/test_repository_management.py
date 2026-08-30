from __future__ import annotations

from datetime import datetime, timezone

import lancedb

from mapce.application.repositories import delete_code_repository, review_code_repository
from mapce.core.code_repositories import make_association_row
from mapce.db import init_chunks, init_code_repos, init_index_meta, init_mapping
from mapce.db.operations import upsert_code_repo
from mapce.db.schema import CHUNKS_SCHEMA, INDEX_META_SCHEMA, MAPPING_SCHEMA


def _row(schema, **values):
    row = {field.name: None for field in schema}
    row.update(values)
    return row


def _database(tmp_path, monkeypatch):
    monkeypatch.setenv("MAPCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MAPCE_RUNTIME_DIR", str(tmp_path / "runtime"))
    db = lancedb.connect(tmp_path / "db")
    init_index_meta(db).add(
        [
            _row(
                INDEX_META_SCHEMA,
                paper_id="paper-one",
                title="Paper One",
                authors=["Ada"],
                indexed_at=datetime.now(timezone.utc).isoformat(),
                chunk_count=1,
                has_code=True,
                code_repo_url="https://github.com/acme/code",
                code_indexed=False,
                code_status="needs_review",
                status="complete",
            )
        ]
    )
    repos = init_code_repos(db)
    upsert_code_repo(
        repos,
        make_association_row(
            "paper-one",
            "https://github.com/acme/code",
            source="paper",
            confidence="medium",
            score=3,
            evidence="candidate",
            is_primary=True,
            status="candidate",
        ),
    )
    return db


def test_ignoring_only_candidate_sets_no_code_and_is_idempotent(tmp_path, monkeypatch):
    db = _database(tmp_path, monkeypatch)

    first = review_code_repository(
        "paper-one", "https://github.com/acme/code.git", "ignore", db=db
    )
    second = review_code_repository(
        "paper-one", "https://github.com/acme/code", "ignore", db=db
    )

    assert first["status"] == "ok"
    assert first["code_status"] == "no_code"
    assert second["repositories"][0]["status"] == "ignored"
    meta = init_index_meta(db).search().where("paper_id = 'paper-one'").limit(1).to_list()[0]
    assert meta["has_code"] is False
    assert meta["code_repo_url"] is None


def test_primary_action_switches_repository_without_duplicates(tmp_path, monkeypatch):
    db = _database(tmp_path, monkeypatch)
    repos = init_code_repos(db)
    upsert_code_repo(
        repos,
        make_association_row(
            "paper-one",
            "https://github.com/acme/other",
            source="user",
            confidence="high",
            score=10,
            evidence="user",
            is_primary=False,
            status="pending",
        ),
    )

    result = review_code_repository(
        "paper-one", "https://github.com/acme/other", "set_primary", db=db
    )

    assert result["status"] == "ok"
    assert sum(bool(row["is_primary"]) for row in result["repositories"]) == 1
    assert next(row for row in result["repositories"] if row["is_primary"])["repo_url"].endswith("/other")
    assert repos.count_rows() == 2


def test_delete_repository_removes_owned_chunks_and_mapping(tmp_path, monkeypatch):
    db = _database(tmp_path, monkeypatch)
    vector = [0.0] * 1024
    init_chunks(db).add(
        [
            _row(
                CHUNKS_SCHEMA,
                chunk_id="code:acme__code:file.py:0",
                chunk_type="code_function",
                source_type="code",
                paper_id="paper-one",
                content="def method(): pass",
                fulltext_search="def method pass",
                embedding=vector,
                repo_name="code",
                repo_url="https://github.com/acme/code",
                file_path="file.py",
                language="python",
                symbol_name="method",
                chunk_index=0,
            )
        ]
    )
    init_mapping(db).add(
        [
            _row(
                MAPPING_SCHEMA,
                mapping_id="m1",
                paper_id="paper-one",
                paper_method="Method",
                code_chunk_id="code:acme__code:file.py:0",
                repo_name="code",
                confidence="high",
                evidence="manual",
                created_by="manual",
                verified=True,
            )
        ]
    )

    result = delete_code_repository(
        "paper-one", "https://github.com/acme/code", db=db
    )

    assert result["status"] == "ok"
    assert result["chunks_deleted"] == 1
    assert result["mappings_deleted"] == 1
    assert result["repositories"] == []
    assert result["code_status"] == "no_code"
