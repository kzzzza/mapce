"""Paper chunker — produces L1/L2/L3 + Figure/Table chunks from MinerU output.

Follows the 3-layer + 2 special-block strategy defined in the plan:
  L1: title + abstract + keywords  (~200-500 tokens)  — coarse screening
  L2: per-section chunks           (~500-2000 tokens) — fine ranking
  L3: per-paragraph chunks         (~200-500 tokens)  — prompt injection
  Special: Figure / Table           caption-based embedding
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from mapce.mineru.parser import MinerUOutput

# Approximate token count (char-based heuristic: ~4 chars/token for English)
_CHARS_PER_TOKEN = 4
L2_MAX_CHARS = 8000   # ~2000 tokens
L3_MAX_CHARS = 2000   # ~500 tokens


def _make_chunk_id(paper_id: str, chunk_type: str, index: int) -> str:
    return f"paper:{paper_id}:{chunk_type}:{index}"


def _estimate_tokens(text: str) -> int:
    return len(text) // _CHARS_PER_TOKEN


def _split_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs by double-newline or single-newline boundaries."""
    # Split on blank lines first
    raw = re.split(r"\n\s*\n", text.strip())
    # Merge very short fragments with neighbors
    result = []
    for para in raw:
        para = para.strip()
        if not para:
            continue
        if len(para) < 50 and result:
            result[-1] += "\n" + para
        else:
            result.append(para)
    return result


def _slugify(text: str) -> str:
    """Generate a URL-safe slug from text."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "_", text)
    return text[:80]


def generate_paper_id(
    arxiv_id: str | None = None,
    doi: str | None = None,
    title: str = "",
    first_author: str = "",
    year: int | str = "",
) -> str:
    """Generate a stable paper_id.

    Priority: arxiv_id > doi-derived > slug from title+author+year.
    """
    if arxiv_id:
        return arxiv_id
    if doi:
        return "doi_" + _slugify(doi)
    # Fallback: author_year_title
    author_slug = _slugify(first_author.split()[-1] if first_author else "unknown")
    title_slug = _slugify(title)[:60]
    return f"{author_slug}{year}_{title_slug}"


def chunk_paper(
    paper_dir: Path,
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    """Chunk a single parsed paper directory into all chunk types.

    Args:
        paper_dir: Path to MinerU-parsed paper directory.
        metadata: Paper metadata dict with keys:
            title, authors (list[str]), year, venue, arxiv_id, doi, keywords (list[str]).

    Returns:
        List of chunk dicts ready for LanceDB insertion. Embedding not yet computed.
    """
    mineru = MinerUOutput(paper_dir)
    paper_id = generate_paper_id(
        arxiv_id=metadata.get("arxiv_id"),
        doi=metadata.get("doi"),
        title=metadata.get("title", ""),
        first_author=metadata["authors"][0] if metadata.get("authors") else "",
        year=metadata.get("year", ""),
    )

    chunks: list[dict[str, Any]] = []
    chunk_counter = 0

    title = metadata.get("title", "Untitled")
    authors = metadata.get("authors", [])
    year = metadata.get("year")
    venue = metadata.get("venue", "")
    arxiv_id = metadata.get("arxiv_id")
    doi = metadata.get("doi")
    keywords = metadata.get("keywords", [])

    base_fields = {
        "paper_id": paper_id,
        "source_type": "paper",
        "title": title,
        "authors": authors,
        "year": year,
        "venue": venue,
        "arxiv_id": arxiv_id,
        "doi": doi,
    }

    # ---- L1: Paper-level (title + abstract) ----

    sections = mineru.extract_sections()
    abstract_text = ""
    for sec in sections:
        if sec["heading"].lower() in ("abstract", "abstract."):
            abstract_text = sec["content"]
            break
    # Fallback: first section if no explicit abstract found
    if not abstract_text and sections:
        abstract_text = sections[0]["content"]

    kw_str = ", ".join(keywords) if keywords else ""
    l1_content = f"# {title}\n\n{abstract_text}"
    if kw_str:
        l1_content += f"\n\nKeywords: {kw_str}"

    chunk_id = _make_chunk_id(paper_id, "l1", 0)
    chunks.append({
        "chunk_id": chunk_id,
        "chunk_type": "paper_l1",
        "content": l1_content,
        "section_path": "title+abstract",
        "section_level": 1,
        "chunk_index": 0,
        "prev_chunk_id": None,
        "next_chunk_id": _make_chunk_id(paper_id, "l2", 0) if sections else None,
        **base_fields,
    })
    chunk_counter += 1

    # ---- L2: Section-level chunks ----

    l2_start_index = chunk_counter
    prev_l3_first_id: str | None = None  # track last L3 chunk ID for chaining

    for i, sec in enumerate(sections):
        sec_content = sec["content"]
        heading = sec["heading"]
        level = sec.get("level", 2)

        # Truncate L2 content to ~2000 tokens
        if len(sec_content) > L2_MAX_CHARS:
            sec_content = sec_content[:L2_MAX_CHARS] + "\n\n[... section truncated ...]"

        l2_id = _make_chunk_id(paper_id, "l2", chunk_counter)
        section_path = heading
        chunks.append({
            "chunk_id": l2_id,
            "chunk_type": "paper_l2",
            "content": f"## {heading}\n\n{sec_content}",
            "section_path": section_path,
            "section_level": 2,
            "chunk_index": chunk_counter,
            "prev_chunk_id": _make_chunk_id(paper_id, "l2", chunk_counter - 1) if chunk_counter > l2_start_index else None,
            "next_chunk_id": None,  # will be set when the next one is created
            **base_fields,
        })
        # Fix previous L2's next_chunk_id
        if chunk_counter > l2_start_index:
            chunks[-2]["next_chunk_id"] = l2_id

        chunk_counter += 1

        # ---- L3: Paragraph-level chunks within this section ----

        paragraphs = _split_paragraphs(sec["content"])
        l3_ids: list[str] = []

        for j, para in enumerate(paragraphs):
            if len(para) > L3_MAX_CHARS:
                para = para[:L3_MAX_CHARS] + "\n[... paragraph truncated ...]"

            l3_id = _make_chunk_id(paper_id, "l3", chunk_counter)
            l3_ids.append(l3_id)
            chunks.append({
                "chunk_id": l3_id,
                "chunk_type": "paper_l3",
                "content": para,
                "section_path": f"{section_path} > p{j}",
                "section_level": 3,
                "chunk_index": chunk_counter,
                "prev_chunk_id": l3_ids[j - 1] if j > 0 else (prev_l3_first_id),
                "next_chunk_id": None,
                **base_fields,
            })
            # Fix previous L3's next
            if j > 0:
                chunks[-2]["next_chunk_id"] = l3_id
            elif prev_l3_first_id:
                # Link last L3 of previous section to first L3 of this section
                # Find and update the previous last L3
                for c in reversed(chunks[:-1]):
                    if c["chunk_type"] == "paper_l3" and c["paper_id"] == paper_id:
                        if c["next_chunk_id"] is None:
                            c["next_chunk_id"] = l3_id
                        break
            chunk_counter += 1

        if l3_ids:
            prev_l3_first_id = l3_ids[0]

    # ---- Special: Figures & Tables ----

    ft = mineru.extract_figures_and_tables()

    for fig in ft["figures"]:
        fig_id = _make_chunk_id(paper_id, "fig", chunk_counter)
        image_ref = fig.get("image_ref")
        chunks.append({
            "chunk_id": fig_id,
            "chunk_type": "figure",
            "content": f"Figure {fig['index']}: {fig['caption']}",
            "section_path": f"Figure {fig['index']}",
            "section_level": 99,
            "chunk_index": chunk_counter,
            "prev_chunk_id": None,
            "next_chunk_id": None,
            "figure_path": image_ref,
            "figure_index": fig["index"],
            **base_fields,
        })
        chunk_counter += 1

    # Load detailed table data from MinerU JSON (HTML, images, captions)
    table_data = mineru.extract_table_data()

    for tbl in ft["tables"]:
        tbl_id = _make_chunk_id(paper_id, "tbl", chunk_counter)
        tbl_idx = tbl["index"]
        td = table_data.get(tbl_idx, {})

        # Build rich content: caption + HTML table (strip tags for embedding)
        html = td.get("html", "")
        # Convert HTML to plain-ish text for embedding/search
        import re as _re
        plain_table = _re.sub(r"<[^>]+>", " ", html)  # strip tags
        plain_table = _re.sub(r"\s+", " ", plain_table).strip()

        content = f"Table {tbl_idx}: {tbl['caption']}"
        if plain_table:
            content += f"\n\n{plain_table}"

        # Table image from MinerU JSON
        table_img = td.get("image_path")
        # Fall back to markdown-based image ref
        if not table_img:
            table_img = tbl.get("image_ref")
        # Resolve to full path if available
        if table_img and not table_img.startswith("/"):
            table_img = str(mineru.paper_dir / table_img)

        table_dims = td.get("bbox", [])
        # bbox is [x, y, w, h] in MinerU — compute approximate rows × cols
        if table_dims and len(table_dims) == 4:
            dims_str = f"{table_dims[2] - table_dims[0]:.0f}x{table_dims[3] - table_dims[1]:.0f}"
        else:
            dims_str = None

        chunks.append({
            "chunk_id": tbl_id,
            "chunk_type": "table",
            "content": content,
            "section_path": f"Table {tbl_idx}",
            "section_level": 99,
            "chunk_index": chunk_counter,
            "prev_chunk_id": None,
            "next_chunk_id": None,
            "table_markdown": plain_table if plain_table else None,
            "table_image": table_img,
            "table_dims": dims_str,
            **base_fields,
        })
        chunk_counter += 1

    return chunks
