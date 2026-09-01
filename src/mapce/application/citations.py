"""Structured citation export for indexed papers."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import lancedb

from mapce.db import get_connection, sql_str


_CITATION_COLUMNS = [
    "paper_id",
    "title",
    "authors",
    "year",
    "venue",
    "arxiv_id",
    "doi",
]


def _ascii_token(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9]+", "", ascii_value)


def _citation_key(metadata: dict[str, Any]) -> str:
    authors = metadata.get("authors") or []
    first_author = str(authors[0]) if authors else ""
    family_name = first_author.rsplit(maxsplit=1)[-1] if first_author else ""
    author_token = _ascii_token(family_name)
    year_token = str(metadata.get("year") or "")
    title_words = re.findall(r"[A-Za-z0-9]+", str(metadata.get("title") or ""))
    title_token = next((_ascii_token(word) for word in title_words if len(word) > 2), "")
    key = f"{author_token}{year_token}{title_token}"
    if key:
        return key
    fallback = _ascii_token(str(metadata.get("arxiv_id") or metadata.get("paper_id") or "paper"))
    return fallback or "paper"


def _bibtex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
    }
    return "".join(replacements.get(char, char) for char in value)


def _paper_url(doi: str | None, arxiv_id: str | None) -> str | None:
    if doi:
        return f"https://doi.org/{doi}"
    if arxiv_id:
        return f"https://arxiv.org/abs/{arxiv_id}"
    return None


def build_paper_citation(metadata: dict[str, Any]) -> dict[str, Any]:
    """Build deterministic citation formats from stored metadata only."""
    paper_id = str(metadata.get("paper_id") or "")
    title = str(metadata.get("title") or "")
    authors = [str(author) for author in metadata.get("authors") or []]
    year = metadata.get("year")
    venue = str(metadata.get("venue") or "")
    arxiv_id = str(metadata.get("arxiv_id") or "") or None
    doi = str(metadata.get("doi") or "") or None
    url = _paper_url(doi, arxiv_id)
    citation_key = _citation_key(metadata)

    plain_parts: list[str] = []
    if authors:
        plain_parts.append(", ".join(authors))
    if title:
        plain_parts.append(title)
    if venue:
        plain_parts.append(venue)
    if year is not None:
        plain_parts.append(str(year))
    if doi:
        plain_parts.append(f"https://doi.org/{doi}")
    elif arxiv_id:
        plain_parts.append(f"arXiv:{arxiv_id}")
    plain_text = ". ".join(part.rstrip(".") for part in plain_parts) + ("." if plain_parts else "")

    bibtex_fields: list[tuple[str, str]] = []
    if authors:
        bibtex_fields.append(("author", " and ".join(_bibtex_escape(author) for author in authors)))
    if title:
        bibtex_fields.append(("title", "{" + _bibtex_escape(title) + "}"))
    if year is not None:
        bibtex_fields.append(("year", str(year)))
    if venue:
        bibtex_fields.append(("howpublished", _bibtex_escape(venue)))
    if doi:
        bibtex_fields.append(("doi", _bibtex_escape(doi)))
    if arxiv_id:
        bibtex_fields.extend([
            ("eprint", _bibtex_escape(arxiv_id)),
            ("archivePrefix", "arXiv"),
        ])
    if url:
        bibtex_fields.append(("url", _bibtex_escape(url)))
    field_lines = ",\n".join(
        f"  {name} = {{{value}}}" for name, value in bibtex_fields
    )
    bibtex = f"@misc{{{citation_key},\n{field_lines}\n}}"

    csl_json: dict[str, Any] = {
        "id": paper_id,
        "type": "article",
        "title": title,
        "author": [{"literal": author} for author in authors],
    }
    if year is not None:
        csl_json["issued"] = {"date-parts": [[int(year)]]}
    if venue:
        csl_json["container-title"] = venue
    if doi:
        csl_json["DOI"] = doi
    if url:
        csl_json["URL"] = url

    missing_fields = [
        name
        for name, value in (
            ("title", title),
            ("authors", authors),
            ("year", year),
            ("venue", venue),
            ("identifier", doi or arxiv_id),
        )
        if not value
    ]
    return {
        "paper_id": paper_id,
        "title": title,
        "authors": authors,
        "year": year,
        "venue": venue,
        "arxiv_id": arxiv_id,
        "doi": doi,
        "url": url,
        "citation_key": citation_key,
        "plain_text": plain_text,
        "bibtex": bibtex,
        "csl_json": csl_json,
        "verification_status": "stored_metadata_only",
        "missing_fields": missing_fields,
    }


def get_paper_citation(
    paper_id: str,
    db: lancedb.DBConnection | None = None,
) -> dict[str, Any]:
    """Return citation data for one indexed paper without network access."""
    db = db or get_connection()
    try:
        table = db.open_table("chunks")
        rows = (
            table.search()
            .where(
                f"paper_id = {sql_str(paper_id)} AND chunk_type = 'paper_l1'",
                prefilter=True,
            )
            .select(_CITATION_COLUMNS)
            .limit(1)
            .to_list()
        )
    except Exception:
        rows = []
    if not rows:
        return {
            "status": "error",
            "error_code": "paper_not_found",
            "message": f"Paper not found: {paper_id}",
        }
    return {"status": "ok", **build_paper_citation(rows[0])}
