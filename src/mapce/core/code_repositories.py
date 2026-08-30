"""Paper-to-code-repository discovery and state aggregation."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import lancedb

from mapce.db import (
    ensure_index_meta_code_columns,
    get_connection,
    get_meta,
    init_code_repos,
    init_index_meta,
    list_code_repos,
    upsert_code_repo,
    upsert_meta,
)

CODE_STATUSES = {
    "not_checked", "no_code", "needs_review", "pending",
    "indexing", "indexed", "failed",
}
REPO_STATUSES = {"candidate", "pending", "indexing", "indexed", "failed", "ignored"}

_GITHUB_URL_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])(?:https?://)?(?:www\.)?github\.com/"
    r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"
    r"(?:\.git)?(?:[?#][^\s<>\]\[)('\\\"]*)?",
    re.IGNORECASE,
)
_REFERENCES_RE = re.compile(
    r"^\s*#{1,6}\s*(?:references|bibliography)\b", re.IGNORECASE | re.MULTILINE
)
_OFFICIAL_RE = re.compile(
    r"\b(?:our\s+code|official\s+implementation|code\s+is\s+available|"
    r"project\s+page|we\s+release|we\s+released|we\s+provide)\b",
    re.IGNORECASE,
)
_DEPENDENCY_RE = re.compile(
    r"\b(?:based\s+on|built\s+on|using|adapted\s+from)\b", re.IGNORECASE
)
_TITLE_STOP_WORDS = {
    "with", "from", "using", "based", "towards", "through", "via", "for",
    "the", "and", "into", "over", "under", "paper", "method", "model",
    "learning", "neural", "network", "networks", "deep", "approach", "system",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_github_url(url: str) -> str | None:
    """Return a canonical GitHub owner/repo URL, or None for unsupported URLs."""
    value = (url or "").strip().rstrip(".,;:!?)]}'\"")
    if not value:
        return None
    if not re.match(r"^https?://", value, re.IGNORECASE):
        value = "https://" + value
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.hostname is None or parsed.hostname.lower() not in {"github.com", "www.github.com"}:
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        return None
    owner, repo = parts[0].lower(), parts[1].lower()
    repo = re.sub(r"\.git$", "", repo, flags=re.IGNORECASE).rstrip(".,;:!?)]}'\"")
    if not owner or not repo:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", owner) or not re.fullmatch(r"[A-Za-z0-9_.-]+", repo):
        return None
    return f"https://github.com/{owner}/{repo}"


def association_id(paper_id: str, repo_url: str) -> str:
    digest = hashlib.sha256(f"{paper_id}\0{repo_url}".encode("utf-8")).hexdigest()[:24]
    return f"repo:{digest}"


def repository_identity(repo_url: str) -> str:
    """Return an owner-aware, filesystem-safe repository identifier."""
    normalized = normalize_github_url(repo_url)
    if normalized is None:
        raise ValueError(f"Unsupported GitHub repository URL: {repo_url}")
    owner, repo = normalized.rsplit("/", 2)[-2:]
    return f"{owner}__{repo}"


def repository_name(repo_url: str) -> str:
    normalized = normalize_github_url(repo_url)
    if normalized is None:
        raise ValueError(f"Unsupported GitHub repository URL: {repo_url}")
    return normalized.rsplit("/", 1)[-1]


def _title_matches_repo(title: str, repo_name: str) -> bool:
    title_tokens = re.findall(r"[a-z0-9]+", title.lower())
    repo_compact = re.sub(r"[^a-z0-9]+", "", repo_name.lower())
    meaningful = [
        token for token in title_tokens
        if len(token) >= 4 and token not in _TITLE_STOP_WORDS and not token.isdigit()
    ]
    acronym_tokens = [
        token for token in title_tokens
        if token not in _TITLE_STOP_WORDS and token not in {"a", "an", "of", "to", "in"}
    ]
    acronym = "".join(token[0] for token in acronym_tokens if token)
    if len(acronym) >= 3 and acronym in repo_compact:
        return True
    return any(token in repo_compact for token in meaningful)


def _score_occurrence(text: str, start: int, end: int, title: str, repo_name: str) -> tuple[int, dict]:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end < 0:
        line_end = len(text)
    context_start = line_start
    # A bare Markdown URL commonly follows an ownership sentence on the
    # preceding line. Include that line only when no prose precedes this URL;
    # this prevents a neighboring official link from boosting a dependency.
    before_on_line = text[line_start:start].strip(" \t>*_`-[]()")
    if not before_on_line and line_start > 0:
        previous_start = text.rfind("\n", 0, line_start - 1) + 1
        context_start = previous_start
    context = text[context_start:line_end]
    ref_match = _REFERENCES_RE.search(text)
    before_references = ref_match is None or start < ref_match.start()
    components: dict[str, int] = {}
    if _OFFICIAL_RE.search(context):
        components["official_context"] = 4
    if before_references:
        components["before_references"] = 2
    else:
        components["after_references"] = -4
    if _title_matches_repo(title, repo_name):
        components["title_match"] = 2
    if start < 2000:
        components["early_mention"] = 1
    if _DEPENDENCY_RE.search(context):
        components["dependency_context"] = -3
    score = sum(components.values())
    return score, {
        "score_components": components,
        "context": re.sub(r"\s+", " ", context).strip()[:500],
    }


def discover_code_repositories(
    markdown: str,
    title: str,
    arxiv_comment: str = "",
) -> list[dict[str, Any]]:
    """Discover and score GitHub repositories from approved local sources."""
    best_by_url: dict[str, dict[str, Any]] = {}
    for source, text in (("paper", markdown or ""), ("arxiv_metadata", arxiv_comment or "")):
        for match in _GITHUB_URL_RE.finditer(text):
            normalized = normalize_github_url(match.group(0))
            if normalized is None:
                continue
            name = repository_name(normalized)
            score, evidence = _score_occurrence(text, match.start(), match.end(), title, name)
            confidence = "high" if score >= 5 else "medium" if score >= 2 else "low"
            candidate = {
                "repo_url": normalized,
                "repo_name": name,
                "source": source,
                "confidence": confidence,
                "score": score,
                "evidence": json.dumps(evidence, ensure_ascii=False),
                "status": "pending" if confidence == "high" else "candidate",
            }
            previous = best_by_url.get(normalized)
            if previous is None or score > previous["score"]:
                best_by_url[normalized] = candidate

    results = sorted(best_by_url.values(), key=lambda item: (-item["score"], item["repo_url"]))
    for index, item in enumerate(results):
        item["is_primary"] = index == 0
    return results


def make_association_row(
    paper_id: str,
    repo_url: str,
    *,
    source: str,
    confidence: str,
    score: int,
    evidence: str | None,
    is_primary: bool,
    status: str,
    existing: dict | None = None,
    error_msg: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_github_url(repo_url)
    if normalized is None:
        raise ValueError(f"Unsupported GitHub repository URL: {repo_url}")
    if confidence not in {"high", "medium", "low"}:
        raise ValueError(f"Invalid repository confidence: {confidence}")
    if status not in REPO_STATUSES:
        raise ValueError(f"Invalid repository status: {status}")
    now = utc_now()
    return {
        "association_id": association_id(paper_id, normalized),
        "paper_id": paper_id,
        "repo_url": normalized,
        "repo_name": repository_name(normalized),
        "source": source,
        "confidence": confidence,
        "score": int(score),
        "evidence": evidence,
        "is_primary": bool(is_primary),
        "status": status,
        "discovered_at": (existing or {}).get("discovered_at") or now,
        "indexed_at": (existing or {}).get("indexed_at"),
        "updated_at": now,
        "error_msg": error_msg,
    }


def save_discovered_repositories(
    paper_id: str,
    candidates: list[dict[str, Any]],
    db: lancedb.DBConnection | None = None,
) -> list[dict]:
    """Persist discovery results without cloning repositories."""
    if db is None:
        db = get_connection()
    table = init_code_repos(db)
    existing_rows = {row["repo_url"]: row for row in list_code_repos(table, paper_id)}
    preserved_primary = next(
        (
            row for row in existing_rows.values()
            if row.get("is_primary") and row.get("source") == "user"
        ),
        None,
    )
    desired_primary_url = next(
        (candidate["repo_url"] for candidate in candidates if candidate.get("is_primary")),
        None,
    )
    if preserved_primary is None and desired_primary_url is not None:
        for row in existing_rows.values():
            if row.get("is_primary") and row.get("repo_url") != desired_primary_url:
                row["is_primary"] = False
                row["updated_at"] = utc_now()
                upsert_code_repo(table, row)
    for candidate in candidates:
        existing = existing_rows.get(candidate["repo_url"])
        status = candidate["status"]
        if existing and existing.get("status") in {"indexing", "indexed", "failed", "ignored"}:
            status = existing["status"]
        preserve_user = existing is not None and existing.get("source") == "user"
        stored_score = (
            max(int(existing.get("score") or 0), candidate["score"])
            if existing is not None
            else candidate["score"]
        )
        row = make_association_row(
            paper_id,
            candidate["repo_url"],
            source="user" if preserve_user else candidate["source"],
            confidence="high" if preserve_user else candidate["confidence"],
            score=stored_score,
            evidence=(existing or {}).get("evidence") if preserve_user else candidate.get("evidence"),
            is_primary=(
                candidate.get("is_primary", False)
                and preserved_primary is None
            ) or (
                preserved_primary is not None
                and preserved_primary.get("repo_url") == candidate["repo_url"]
            ),
            status=status,
            existing=existing,
            error_msg=(existing or {}).get("error_msg") if status == "failed" else None,
        )
        upsert_code_repo(table, row)
    sync_paper_code_state(paper_id, db=db, checked=True)
    return list_code_repos(table, paper_id)


def derive_code_status(rows: list[dict], checked: bool) -> str:
    statuses = {row.get("status") for row in rows}
    if "indexing" in statuses:
        return "indexing"
    if "indexed" in statuses:
        return "indexed"
    if "pending" in statuses:
        return "pending"
    if "failed" in statuses:
        return "failed"
    if "candidate" in statuses:
        return "needs_review"
    return "no_code" if checked else "not_checked"


def sync_paper_code_state(
    paper_id: str,
    db: lancedb.DBConnection | None = None,
    *,
    checked: bool = True,
) -> dict | None:
    """Aggregate repository rows into new and legacy index_meta fields."""
    if db is None:
        db = get_connection()
    meta_table = ensure_index_meta_code_columns(init_index_meta(db))
    meta = get_meta(meta_table, paper_id)
    if meta is None:
        return None
    repo_table = init_code_repos(db)
    rows = list_code_repos(repo_table, paper_id)
    active_rows = [row for row in rows if row.get("status") != "ignored"]
    code_status = derive_code_status(active_rows, checked)
    primary = next(
        (row for row in active_rows if row.get("is_primary")),
        active_rows[0] if active_rows else None,
    )
    indexed_rows = [row for row in active_rows if row.get("status") == "indexed"]
    meta["code_status"] = code_status
    if checked:
        meta["code_checked_at"] = utc_now()
    meta["has_code"] = bool(active_rows)
    meta["code_repo_url"] = primary.get("repo_url") if primary else None
    meta["code_indexed"] = bool(indexed_rows)
    if meta.get("status") == "code_pending":
        meta["status"] = "complete"
    upsert_meta(meta_table, meta)
    return meta


def get_repository_associations(
    paper_id: str,
    db: lancedb.DBConnection | None = None,
) -> list[dict]:
    if db is None:
        db = get_connection()
    try:
        rows = list_code_repos(db.open_table("paper_code_repos"), paper_id)
        return sorted(
            rows,
            key=lambda row: (
                not bool(row.get("is_primary")),
                -int(row.get("score") or 0),
                row.get("repo_url") or "",
            ),
        )
    except Exception:
        return []
