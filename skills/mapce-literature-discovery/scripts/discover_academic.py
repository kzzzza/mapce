#!/usr/bin/env python3
"""Search public academic metadata APIs and produce a deduplicated CSV shortlist."""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


JsonFetcher = Callable[[str], dict[str, Any]]
TextFetcher = Callable[[str], str]


@dataclass
class Candidate:
    title: str
    authors: str = ""
    year: str = ""
    doi: str = ""
    arxiv_id: str = ""
    url: str = ""
    abstract: str = ""
    discovery_source: str = ""
    query: str = ""
    oa_status: str = "unknown"
    index_source: str = ""
    metadata_status: str = "discovered"


def normalize_doi(value: str | None) -> str:
    text = (value or "").strip()
    text = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi\s*:\s*)", "", text, flags=re.I)
    return text.rstrip(".,;)").lower()


def normalize_arxiv_id(value: str | None) -> str:
    text = (value or "").strip()
    text = re.sub(r"^(?:arxiv\s*:|https?://[^/]*arxiv\.org/(?:abs|pdf)/)", "", text, flags=re.I)
    text = re.sub(r"\.pdf$", "", text, flags=re.I)
    return re.sub(r"v\d+$", "", text)


def normalize_title(value: str) -> str:
    text = unicodedata.normalize("NFKC", html.unescape(value)).casefold()
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def _request(url: str) -> bytes:
    contact = os.environ.get("MAPCE_CONTACT_EMAIL", "")
    agent = "MAPCE-Research-Skills/0.1"
    if contact:
        agent += f" (mailto:{contact})"
    request = urllib.request.Request(url, headers={"User-Agent": agent})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def fetch_json(url: str) -> dict[str, Any]:
    return json.loads(_request(url).decode("utf-8"))


def fetch_text(url: str) -> str:
    return _request(url).decode("utf-8")


def search_arxiv(query: str, limit: int, *, fetcher: TextFetcher = fetch_text) -> list[Candidate]:
    params = urllib.parse.urlencode({
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": limit,
        "sortBy": "relevance",
        "sortOrder": "descending",
    })
    root = ET.fromstring(fetcher(f"https://export.arxiv.org/api/query?{params}"))
    ns = {"a": "http://www.w3.org/2005/Atom"}
    results: list[Candidate] = []
    for entry in root.findall("a:entry", ns):
        def value(tag: str) -> str:
            element = entry.find(f"a:{tag}", ns)
            return " ".join((element.text or "").split()) if element is not None else ""

        identifier = normalize_arxiv_id(value("id"))
        authors = "; ".join(
            " ".join((name.text or "").split())
            for name in entry.findall("a:author/a:name", ns)
        )
        published = value("published")
        results.append(Candidate(
            title=value("title"), authors=authors, year=published[:4],
            arxiv_id=identifier, url=f"https://arxiv.org/abs/{identifier}",
            abstract=value("summary"), discovery_source="arxiv", oa_status="open",
            index_source=identifier, query=query,
        ))
    return results


def _openalex_abstract(inverted: Any) -> str:
    if not isinstance(inverted, dict):
        return ""
    positions: list[tuple[int, str]] = []
    for word, offsets in inverted.items():
        for offset in offsets if isinstance(offsets, list) else []:
            if isinstance(offset, int):
                positions.append((offset, str(word)))
    return " ".join(word for _, word in sorted(positions))


def search_openalex(query: str, limit: int, *, fetcher: JsonFetcher = fetch_json) -> list[Candidate]:
    params = urllib.parse.urlencode({"search": query, "per-page": min(limit, 100)})
    payload = fetcher(f"https://api.openalex.org/works?{params}")
    results: list[Candidate] = []
    for item in payload.get("results", []):
        ids = item.get("ids") or {}
        locations = item.get("best_oa_location") or {}
        primary = item.get("primary_location") or {}
        landing = locations.get("landing_page_url") or primary.get("landing_page_url") or ""
        pdf_url = locations.get("pdf_url") or ""
        arxiv_id = ""
        for value in ids.values():
            if isinstance(value, str) and "arxiv.org" in value:
                arxiv_id = normalize_arxiv_id(value)
                break
        authors = "; ".join(
            str((entry.get("author") or {}).get("display_name") or "")
            for entry in item.get("authorships", [])
            if (entry.get("author") or {}).get("display_name")
        )
        is_oa = bool((item.get("open_access") or {}).get("is_oa"))
        index_source = arxiv_id or pdf_url
        results.append(Candidate(
            title=str(item.get("display_name") or item.get("title") or ""),
            authors=authors,
            year=str(item.get("publication_year") or ""),
            doi=normalize_doi(ids.get("doi") or item.get("doi")),
            arxiv_id=arxiv_id,
            url=str(landing),
            abstract=_openalex_abstract(item.get("abstract_inverted_index")),
            discovery_source="openalex",
            query=query,
            oa_status="open" if is_oa else "closed_or_unknown",
            index_source=index_source,
        ))
    return results


def crossref_metadata(doi: str, *, fetcher: JsonFetcher = fetch_json) -> dict[str, Any]:
    normalized = normalize_doi(doi)
    if not normalized:
        return {}
    url = "https://api.crossref.org/works/" + urllib.parse.quote(normalized, safe="")
    return dict(fetcher(url).get("message") or {})


def enrich_crossref(candidates: list[Candidate], limit: int, *, fetcher: JsonFetcher = fetch_json) -> None:
    checked = 0
    for candidate in candidates:
        if not candidate.doi or checked >= limit:
            continue
        metadata = crossref_metadata(candidate.doi, fetcher=fetcher)
        checked += 1
        titles = metadata.get("title") or []
        if not candidate.title and titles:
            candidate.title = str(titles[0])
        if not candidate.year:
            parts = ((metadata.get("published") or {}).get("date-parts") or [[]])[0]
            candidate.year = str(parts[0]) if parts else ""
        if metadata:
            candidate.metadata_status = "authority_checked"
        time.sleep(0.05)


def _identities(candidate: Candidate) -> list[tuple[str, ...]]:
    identities: list[tuple[str, ...]] = []
    if candidate.doi:
        identities.append(("doi", normalize_doi(candidate.doi)))
    if candidate.arxiv_id:
        identities.append(("arxiv", normalize_arxiv_id(candidate.arxiv_id)))
    identities.append(("title_year", normalize_title(candidate.title), str(candidate.year)))
    return identities


def deduplicate(candidates: list[Candidate]) -> list[Candidate]:
    merged: list[Candidate] = []
    aliases: dict[tuple[str, ...], Candidate] = {}
    for candidate in candidates:
        identities = _identities(candidate)
        matches: list[Candidate] = []
        for key in identities:
            match = aliases.get(key)
            if match is not None and all(match is not value for value in matches):
                matches.append(match)
        if not matches:
            merged.append(candidate)
            for key in identities:
                aliases[key] = candidate
            continue
        existing = matches[0]
        source_values = {
            value
            for row in [*matches, candidate]
            for value in row.discovery_source.split("+")
            if value
        }
        query_values = {
            value
            for row in [*matches, candidate]
            for value in row.query.split(" | ")
            if value
        }
        for duplicate in matches[1:]:
            if duplicate in merged:
                merged.remove(duplicate)
            for alias, value in list(aliases.items()):
                if value is duplicate:
                    aliases[alias] = existing
            for field in ("title", "authors", "year", "doi", "arxiv_id", "url", "abstract", "index_source"):
                if not getattr(existing, field) and getattr(duplicate, field):
                    setattr(existing, field, getattr(duplicate, field))
        existing.discovery_source = "+".join(sorted(source_values))
        existing.query = " | ".join(sorted(query_values))
        for field in ("title", "authors", "year", "doi", "arxiv_id", "url", "abstract", "index_source"):
            if not getattr(existing, field) and getattr(candidate, field):
                setattr(existing, field, getattr(candidate, field))
        if candidate.oa_status == "open":
            existing.oa_status = "open"
        for key in _identities(existing) + identities:
            aliases[key] = existing
    return merged


def write_csv(path: Path, candidates: list[Candidate]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(Candidate.__dataclass_fields__)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(asdict(candidate) for candidate in candidates)


def append_search_log(
    path: Path,
    *,
    query: str,
    sources: list[str],
    result_count: int,
    errors: list[dict[str, str]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "searched_at": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "sources": sources,
        "result_count": result_count,
        "errors": errors,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--sources", default="arxiv,openalex")
    parser.add_argument("--crossref-limit", type=int, default=10)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--log", type=Path)
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 100:
        parser.error("--limit must be between 1 and 100")

    candidates: list[Candidate] = []
    errors: list[dict[str, str]] = []
    for source in [value.strip() for value in args.sources.split(",") if value.strip()]:
        try:
            if source == "arxiv":
                candidates.extend(search_arxiv(args.query, args.limit))
            elif source == "openalex":
                candidates.extend(search_openalex(args.query, args.limit))
            else:
                raise ValueError(f"Unknown source: {source}")
        except Exception as exc:
            errors.append({"source": source, "error": str(exc)})
    candidates = deduplicate(candidates)
    try:
        enrich_crossref(candidates, max(0, args.crossref_limit))
    except Exception as exc:
        errors.append({"source": "crossref", "error": str(exc)})
    write_csv(args.output, candidates)
    if args.log is not None:
        append_search_log(
            args.log,
            query=args.query,
            sources=[value.strip() for value in args.sources.split(",") if value.strip()],
            result_count=len(candidates),
            errors=errors,
        )
    print(json.dumps({
        "status": "ok" if candidates else "no_results",
        "count": len(candidates),
        "output": str(args.output),
        "errors": errors,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
