"""arXiv data source adapter.

Supports:
  - Downloading PDFs by arXiv ID
  - Searching arXiv by query
  - Extracting metadata from arXiv API
"""

from __future__ import annotations

import json
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ArxivPaper:
    """Metadata for an arXiv paper."""
    arxiv_id: str
    title: str
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    published: str = ""  # YYYY-MM-DD
    updated: str = ""
    categories: list[str] = field(default_factory=list)
    pdf_url: str = ""
    comment: str = ""


# ---------------------------------------------------------------------------
# arXiv API (free, no key required, rate-limited)
# ---------------------------------------------------------------------------

ARXIV_API = "http://export.arxiv.org/api/query"


def search_arxiv(
    query: str,
    max_results: int = 10,
    start: int = 0,
) -> list[ArxivPaper]:
    """Search arXiv by query string.

    Args:
        query: Search query (supports arXiv API syntax).
        max_results: Max papers to return.
        start: Offset for pagination.

    Returns:
        List of ArxivPaper metadata objects.
    """
    params = urllib.parse.urlencode({
        "search_query": query,
        "start": start,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    url = f"{ARXIV_API}?{params}"

    req = urllib.request.Request(url, headers={"User-Agent": "MAPCE/0.1"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")

    return _parse_arxiv_response(raw)


def get_arxiv_metadata(arxiv_id: str) -> ArxivPaper | None:
    """Fetch metadata for a single arXiv paper by ID."""
    results = search_arxiv(f"id:{arxiv_id}", max_results=1)
    return results[0] if results else None


def download_arxiv_pdf(arxiv_id: str, output_dir: Path) -> Path:
    """Download the PDF for an arXiv paper.

    Args:
        arxiv_id: arXiv paper ID (e.g. "2301.12345").
        output_dir: Directory to save the PDF.

    Returns:
        Path to the downloaded PDF file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = output_dir / f"{arxiv_id}.pdf"

    if pdf_path.exists():
        return pdf_path

    url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    urllib.request.urlretrieve(url, pdf_path)

    return pdf_path


def _parse_arxiv_response(xml_str: str) -> list[ArxivPaper]:
    """Parse arXiv API Atom XML response into ArxivPaper objects."""
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    root = ET.fromstring(xml_str)
    papers = []

    for entry in root.findall("atom:entry", ns):
        arxiv_id = entry.find("atom:id", ns)
        arxiv_id_text = arxiv_id.text.strip() if arxiv_id is not None else ""
        # Extract ID from URL: http://arxiv.org/abs/2301.12345v1 → 2301.12345
        arxiv_id_clean = arxiv_id_text.split("/")[-1].split("v")[0] if arxiv_id_text else ""

        title = entry.find("atom:title", ns)
        title_text = title.text.strip().replace("\n", " ") if title is not None else ""

        abstract = entry.find("atom:summary", ns)
        abstract_text = abstract.text.strip().replace("\n", " ") if abstract is not None else ""

        authors = []
        for author in entry.findall("atom:author", ns):
            name = author.find("atom:name", ns)
            if name is not None and name.text:
                authors.append(name.text.strip())

        published = entry.find("atom:published", ns)
        published_text = published.text.strip()[:10] if published is not None else ""

        updated = entry.find("atom:updated", ns)
        updated_text = updated.text.strip()[:10] if updated is not None else ""

        categories = []
        for cat in entry.findall("atom:category", ns):
            term = cat.get("term", "")
            if term:
                categories.append(term)

        pdf_url = ""
        for link in entry.findall("atom:link", ns):
            if link.get("title") == "pdf":
                pdf_url = link.get("href", "")
                break

        comment = entry.find("arxiv:comment", ns)
        comment_text = comment.text.strip() if comment is not None and comment.text else ""

        papers.append(ArxivPaper(
            arxiv_id=arxiv_id_clean,
            title=title_text,
            authors=authors,
            abstract=abstract_text,
            published=published_text,
            updated=updated_text,
            categories=categories,
            pdf_url=pdf_url,
            comment=comment_text,
        ))

    return papers


# ---------------------------------------------------------------------------
# Integration helper: search + index in one flow
# ---------------------------------------------------------------------------

def search_and_index_arxiv(
    query: str,
    max_results: int = 5,
    output_dir: Path | None = None,
    language: str = "en",
) -> list[dict[str, Any]]:
    """Search arXiv and index matching papers.

    Args:
        query: arXiv search query.
        max_results: Max papers to index.
        output_dir: Temp dir for downloads.
        language: Paper language.

    Returns:
        List of indexing results: {"arxiv_id": str, "paper_id": str, "status": str}.
    """
    import tempfile
    from mapce.core.indexing import index_paper

    papers = search_arxiv(query, max_results=max_results)

    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="mapce_arxiv_batch_"))

    results = []
    for paper in papers:
        try:
            pdf_path = download_arxiv_pdf(paper.arxiv_id, output_dir)
            metadata = {
                "title": paper.title,
                "authors": paper.authors,
                "year": int(paper.published[:4]) if paper.published else None,
                "venue": "arXiv",
                "arxiv_id": paper.arxiv_id,
                "doi": None,
                "keywords": paper.categories,
            }
            paper_id = index_paper(
                pdf_path=pdf_path,
                metadata=metadata,
                language=language,
            )
            results.append({
                "arxiv_id": paper.arxiv_id,
                "paper_id": paper_id,
                "status": "ok",
            })
        except Exception as e:
            results.append({
                "arxiv_id": paper.arxiv_id,
                "paper_id": None,
                "status": "failed",
                "error": str(e),
            })

    return results
