"""Lightweight paper-source detection shared by TUI and backend validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlparse

PaperSourceType = Literal["local", "arxiv", "url"]

_NEW_ARXIV_ID = re.compile(r"\d{4}\.\d{4,5}(?:v\d+)?", re.IGNORECASE)
_LEGACY_ARXIV_ID = re.compile(
    r"[a-z][a-z0-9.-]*(?:/[a-z][a-z0-9.-]*)?/\d{7}(?:v\d+)?",
    re.IGNORECASE,
)
_ARXIV_PREFIX = re.compile(r"^arxiv[\s:_-]*", re.IGNORECASE)
_VALID_TYPES = frozenset({"local", "arxiv", "url"})


class PaperSourceError(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True)
class DetectedPaperSource:
    source_type: PaperSourceType
    normalized_source: str


def _strip_wrapping_quotes(value: str) -> str:
    candidate = value.strip()
    if (
        len(candidate) >= 2
        and candidate[0] == candidate[-1]
        and candidate[0] in {'"', "'"}
    ):
        return candidate[1:-1].strip()
    return candidate


def normalize_arxiv_id(value: str) -> str | None:
    """Normalize arXiv IDs, arXiv URLs, and optional ``arxiv`` prefixes."""
    candidate = _strip_wrapping_quotes(value)
    if not candidate:
        return None
    if "arxiv.org" in candidate.lower():
        try:
            parsed = urlparse(candidate)
        except ValueError:
            return None
        if parsed.hostname not in {"arxiv.org", "www.arxiv.org", "export.arxiv.org"}:
            return None
        path = unquote(parsed.path).strip("/")
        if path.startswith("abs/"):
            candidate = path[4:]
        elif path.startswith("pdf/"):
            candidate = path[4:]
        else:
            return None
    else:
        candidate = _ARXIV_PREFIX.sub("", candidate, count=1)
    candidate = candidate.strip().rstrip("/")
    if candidate.lower().endswith(".pdf"):
        candidate = candidate[:-4]
    candidate = candidate.strip()
    if not (_NEW_ARXIV_ID.fullmatch(candidate) or _LEGACY_ARXIV_ID.fullmatch(candidate)):
        return None
    return re.sub(r"v\d+$", "", candidate, flags=re.IGNORECASE)


def detect_paper_source(value: str) -> DetectedPaperSource | None:
    """Classify a paper source without network or database access."""
    candidate = _strip_wrapping_quotes(value)
    if not candidate:
        return None

    arxiv_id = normalize_arxiv_id(candidate)
    if arxiv_id is not None:
        return DetectedPaperSource("arxiv", arxiv_id)

    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None
    if parsed.scheme.lower() in {"http", "https"} and parsed.hostname:
        return DetectedPaperSource("url", candidate)

    try:
        path = Path(candidate).expanduser()
    except (OSError, RuntimeError, ValueError):
        return None
    looks_like_path = (
        path.suffix.lower() == ".pdf"
        or candidate.startswith(("/", "./", "../", "~/"))
    )
    if not looks_like_path:
        try:
            looks_like_path = path.is_file()
        except OSError:
            return None
    if looks_like_path:
        try:
            normalized = str(path.resolve())
        except (OSError, RuntimeError, ValueError):
            return None
        return DetectedPaperSource("local", normalized)
    return None


def validate_paper_source(value: str, source_type: str) -> DetectedPaperSource:
    """Validate the declared source type before any network operation."""
    if source_type not in _VALID_TYPES:
        raise PaperSourceError(
            "invalid_source_type",
            f"Unknown source_type: {source_type}",
        )
    detected = detect_paper_source(value)
    if detected is None:
        raise PaperSourceError(
            "invalid_paper_source",
            "Paper source must be a local PDF path, arXiv ID, or HTTP(S) URL.",
        )
    if detected.source_type != source_type:
        raise PaperSourceError(
            "source_type_mismatch",
            f"Source looks like {detected.source_type}, but source_type is {source_type}.",
        )
    return detected
