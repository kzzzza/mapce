from __future__ import annotations

import builtins
import json

import pytest

from mapce.paper_sources import (
    PaperSourceError,
    detect_paper_source,
    normalize_arxiv_id,
    validate_paper_source,
)
from mapce.core import indexing
from mapce.mcp import _handlers


@pytest.mark.parametrize(
    ("value", "source_type", "normalized"),
    [
        (
            "/Users/example/Downloads/evolution_of_humanoid_locomotion_control_1203.pdf",
            "local",
            "/Users/example/Downloads/evolution_of_humanoid_locomotion_control_1203.pdf",
        ),
        ("2505.04961", "arxiv", "2505.04961"),
        ("arxiv2505.04961", "arxiv", "2505.04961"),
        ("arXiv:2505.04961v2", "arxiv", "2505.04961"),
        ("https://arxiv.org/pdf/2505.04961.pdf", "arxiv", "2505.04961"),
        ("https://example.org/papers/method.pdf", "url", "https://example.org/papers/method.pdf"),
    ],
)
def test_detect_paper_source(value, source_type, normalized):
    detected = detect_paper_source(value)

    assert detected is not None
    assert detected.source_type == source_type
    assert detected.normalized_source == normalized


def test_normalize_arxiv_id_keeps_legacy_support():
    assert normalize_arxiv_id("https://arxiv.org/abs/hep-th/9901001v2") == "hep-th/9901001"


def test_validate_paper_source_rejects_mismatch_before_work():
    with pytest.raises(PaperSourceError) as error:
        validate_paper_source("/tmp/paper.pdf", "arxiv")

    assert error.value.error_code == "source_type_mismatch"


def test_malformed_url_is_rejected_without_raising():
    assert detect_paper_source("http://[") is None


@pytest.mark.asyncio
async def test_handler_rejects_mismatch_before_importing_indexer(monkeypatch):
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "mapce.core.indexing":
            raise AssertionError("indexing code must not be imported for a mismatched source")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    payload = json.loads(
        await _handlers.index_paper(
            source="/tmp/paper.pdf",
            source_type="arxiv",
        )
    )

    assert payload["status"] == "error"
    assert payload["error_code"] == "source_type_mismatch"


def test_public_url_indexing_uses_url_parser_and_stable_cache(monkeypatch, tmp_path):
    calls = {}
    paper_dir = tmp_path / "parsed"
    paper_dir.mkdir()

    monkeypatch.setattr(
        "mapce.service.runtime.assert_database_write_allowed",
        lambda: None,
    )

    def fake_parse(url, language):
        calls["parse"] = (url, language)
        return {"state": "done", "full_zip_url": "https://cdn.example/result.zip"}

    def fake_download(result, output_dir):
        calls["download"] = (result, output_dir)
        return paper_dir

    monkeypatch.setattr("mapce.mineru.api.parse_from_url", fake_parse)
    monkeypatch.setattr("mapce.mineru.api.download_and_unpack", fake_download)
    monkeypatch.setattr(indexing, "_get_paper_cache_dir", lambda paper_id: tmp_path / paper_id)
    monkeypatch.setattr(
        indexing,
        "_extract_metadata_from_mineru",
        lambda parsed_dir, filename: {"title": filename.stem},
    )
    monkeypatch.setattr(
        indexing,
        "_index_from_mineru_dir",
        lambda parsed_dir, metadata, on_progress=None: metadata["title"],
    )

    paper_id = indexing.index_paper_from_url(
        "https://example.org/papers/method.pdf?download=1",
        language="en",
    )

    assert paper_id == "method"
    assert calls["parse"] == (
        "https://example.org/papers/method.pdf?download=1",
        "en",
    )
    result, output_dir = calls["download"]
    assert result["data_id"].startswith("method-")
    assert result["full_zip_url"] == "https://cdn.example/result.zip"
    assert output_dir == tmp_path
