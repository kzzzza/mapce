"""Four-stage progressive retrieval engine.

Stage 0: Query understanding & routing
Stage 1: Paper-level coarse screening (L1 vector search, top-20)
Stage 2: Section/code localization (L2 fine ranking within top-20)
Stage 3: Context expansion (L3 downward + adjacent + lateral)
Stage 4: Result assembly for prompt injection
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import lancedb

from mapce.core.embedding import embed_single
from mapce.db import get_connection, init_chunks, init_index_meta, sql_in_list, sql_str


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class SearchIntent:
    """Parsed search intent from a user query."""
    intent: str  # "paper_search" | "code_search" | "hybrid"
    sub_type: str  # "general" | "figure_lookup" | "benchmark" | "formula"
    concepts: list[str] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievalResult:
    """A single retrieval hit after expansion."""
    chunk_id: str
    chunk_type: str
    paper_id: str
    title: str
    authors: list[str]
    year: int | None
    venue: str
    section_path: str
    content: str
    score: float

    # Code-specific fields (None for paper-only results)
    repo_name: str | None = None
    file_path: str | None = None
    language: str | None = None
    code_content: str | None = None
    calls: list[str] = field(default_factory=list)
    called_by: list[str] = field(default_factory=list)

    # Special fields
    figure_path: str | None = None
    table_markdown: str | None = None
    config_keys: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Stage 0: Query understanding
# ---------------------------------------------------------------------------

_INTENT_KEYWORDS = {
    "paper_search": [
        "paper", "method", "approach", "model", "algorithm", "architecture",
        "training", "inference", "loss", "equation", "formula", "theorem",
        "experiment", "benchmark", "result", "dataset", "figure", "table",
        "what is", "how does", "explain", "describe", "compare", "difference",
        "state of the art", "sota", "survey", "review",
    ],
    "code_search": [
        "code", "implement", "implementation", "python", "cpp", "pytorch",
        "tensorflow", "ros", "function", "class", "module", "script",
        "run", "execute", "how to code", "write", "programming",
        "repo", "repository", "github", "clone",
    ],
}

_SUB_TYPE_KEYWORDS = {
    "figure_lookup": ["figure", "fig", "diagram", "architecture diagram", "flowchart", "pipeline", "illustration", "plot", "visualization"],
    "benchmark": ["benchmark", "performance", "accuracy", "results", "comparison", "vs", "versus", "outperform", "sota", "table", "score", "metric"],
    "formula": ["formula", "equation", "loss function", "objective", "derivation", "proof", "theorem", "lemma", "math"],
}


def parse_intent(query: str) -> SearchIntent:
    """Simple keyword-based intent parsing.

    For production use, this would be an LLM call. The keyword-based
    approach provides a fast zero-latency baseline.

    Args:
        query: Raw user query string.

    Returns:
        Parsed SearchIntent.
    """
    ql = query.lower()

    # Score each intent
    paper_score = sum(1 for kw in _INTENT_KEYWORDS["paper_search"] if kw in ql)
    code_score = sum(1 for kw in _INTENT_KEYWORDS["code_search"] if kw in ql)

    if paper_score >= code_score and paper_score > 0:
        intent = "paper_search"
    elif code_score > paper_score:
        intent = "code_search"
    else:
        intent = "hybrid"

    # Sub-type
    sub_type = "general"
    for st, kws in _SUB_TYPE_KEYWORDS.items():
        if any(kw in ql for kw in kws):
            sub_type = st
            break

    return SearchIntent(intent=intent, sub_type=sub_type, filters={})


def parse_intent_with_llm(query: str, llm_call=None) -> SearchIntent:
    """Parse intent using an LLM for higher accuracy.

    Args:
        query: Raw user query string.
        llm_call: A callable that takes a prompt string and returns a JSON response.
                  If None, falls back to keyword parsing.

    Returns:
        Parsed SearchIntent.
    """
    if llm_call is None:
        return parse_intent(query)

    prompt = f"""Analyze the following research query and return a JSON object:

Query: "{query}"

Return JSON with these fields:
- intent: "paper_search" | "code_search" | "hybrid"
- sub_type: "general" | "figure_lookup" | "benchmark" | "formula"
- concepts: list of key technical concepts mentioned
- filters: dict of constraints (year_min, year_max, venue, arxiv_category)

Example:
{{"intent": "paper_search", "sub_type": "benchmark", "concepts": ["diffusion policy", "manipulation"], "filters": {{"year_min": 2023}}}}
"""
    try:
        import json
        result = json.loads(llm_call(prompt))
        return SearchIntent(
            intent=result.get("intent", "hybrid"),
            sub_type=result.get("sub_type", "general"),
            concepts=result.get("concepts", []),
            filters=result.get("filters", {}),
        )
    except Exception:
        return parse_intent(query)


# ---------------------------------------------------------------------------
# Search helpers
# ---------------------------------------------------------------------------

def _build_where_clause(filters: dict[str, Any], paper_ids: list[str] | None = None) -> str | None:
    """Build a LanceDB SQL WHERE clause from filters dict + optional paper_id list."""
    parts = []

    if paper_ids:
        parts.append(f"paper_id IN ({sql_in_list(paper_ids)})")

    if "year_min" in filters:
        parts.append(f"year >= {filters['year_min']}")
    if "year_max" in filters:
        parts.append(f"year <= {filters['year_max']}")
    if "venue" in filters:
        parts.append(f"venue = {sql_str(filters['venue'])}")

    # Only return non-deleted paper chunks. Parenthesize the OR so it isn't
    # swallowed by the AND join (otherwise figures/tables from any paper leak).
    parts.append("(chunk_type LIKE 'paper_%' OR chunk_type IN ('figure', 'table'))")

    return " AND ".join(parts) if parts else None


def _row_to_result(row: dict, score: float = 0.0) -> RetrievalResult:
    """Convert a LanceDB row dict to a RetrievalResult."""
    return RetrievalResult(
        chunk_id=row.get("chunk_id", ""),
        chunk_type=row.get("chunk_type", ""),
        paper_id=row.get("paper_id", ""),
        title=row.get("title", ""),
        authors=row.get("authors") or [],
        year=row.get("year"),
        venue=row.get("venue", ""),
        section_path=row.get("section_path", ""),
        content=row.get("content", ""),
        score=score,
        repo_name=row.get("repo_name"),
        file_path=row.get("file_path"),
        language=row.get("language"),
        code_content=row.get("code_content"),
        calls=row.get("calls") or [],
        called_by=row.get("called_by") or [],
        figure_path=row.get("figure_path"),
        table_markdown=row.get("table_markdown"),
        config_keys=row.get("config_keys") or [],
    )


# ---------------------------------------------------------------------------
# Stage 1-4: Progressive retrieval
# ---------------------------------------------------------------------------


def search(
    query: str,
    intent: SearchIntent | None = None,
    top_k_papers: int = 20,
    top_k_chunks: int = 10,
    year_min: int | None = None,
    year_max: int | None = None,
    venue: str | None = None,
    db: lancedb.DBConnection | None = None,
) -> tuple[list[RetrievalResult], SearchIntent]:
    """Run the full 4-stage retrieval pipeline.

    Args:
        query: User query string.
        intent: Pre-parsed intent, or None to auto-parse.
        top_k_papers: Number of papers for Stage 1 coarse screening.
        top_k_chunks: Number of chunks for Stage 2 fine ranking.
        year_min: Optional publication year lower bound.
        year_max: Optional publication year upper bound.
        venue: Optional venue filter.
        db: Optional LanceDB connection.

    Returns:
        (expanded_results, intent) tuple.
    """
    if db is None:
        db = get_connection()

    if intent is None:
        intent = parse_intent(query)
        # Merge explicit filters into intent
        if year_min:
            intent.filters["year_min"] = year_min
        if year_max:
            intent.filters["year_max"] = year_max
        if venue:
            intent.filters["venue"] = venue

    table = init_chunks(db)

    # ---- Stage 1: Coarse screening on L1 chunks ----

    query_emb = embed_single(query)

    l1_where = "chunk_type = 'paper_l1'"
    if intent.filters.get("year_min"):
        l1_where += f" AND year >= {intent.filters['year_min']}"
    if intent.filters.get("year_max"):
        l1_where += f" AND year <= {intent.filters['year_max']}"
    if intent.filters.get("venue"):
        l1_where += f" AND venue = {sql_str(intent.filters['venue'])}"

    try:
        l1_results = (
            table.search(query_emb)
            .where(l1_where)
            .limit(top_k_papers)
            .to_list()
        )
    except Exception:
        # Fallback: try without vector search
        l1_results = (
            table.search()
            .where(l1_where)
            .limit(top_k_papers)
            .to_list()
        )

    paper_ids = [r["paper_id"] for r in l1_results]
    paper_scores = {r["paper_id"]: 1.0 - i / max(len(l1_results), 1) for i, r in enumerate(l1_results)}

    # ---- Stage 2: Fine ranking ----

    if intent.intent == "paper_search":
        # Search L2 *and* L3 chunks within the paper candidate set. L3 paragraphs
        # past the L2 truncation point only exist at L3, so coarse screening must
        # cover them directly; Stage-3 dedup drops anything re-expanded.
        l2_where_parts = ["chunk_type IN ('paper_l2', 'paper_l3')"]
        if paper_ids:
            l2_where_parts.append(f"paper_id IN ({sql_in_list(paper_ids)})")
        l2_where = " AND ".join(l2_where_parts)

        # Pull a wider candidate pool since it now spans two granularities.
        paper_limit = top_k_chunks * 3

        try:
            l2_results = (
                table.search(query_emb)
                .where(l2_where)
                .limit(paper_limit)
                .to_list()
            )
        except Exception:
            l2_results = (
                table.search()
                .where(l2_where)
                .limit(paper_limit)
                .to_list()
            )

    elif intent.intent == "code_search":
        # Search code L2 chunks within papers that have code
        code_where_parts = ["chunk_type IN ('code_l2', 'code_l3')"]
        if paper_ids:
            code_where_parts.append(f"paper_id IN ({sql_in_list(paper_ids)})")
        code_where = " AND ".join(code_where_parts)

        try:
            l2_results = (
                table.search(query_emb)
                .where(code_where)
                .limit(top_k_chunks)
                .to_list()
            )
        except Exception:
            l2_results = (
                table.search()
                .where(code_where)
                .limit(top_k_chunks)
                .to_list()
            )
    else:
        # hybrid: search both
        paper_where = " AND ".join([
            "chunk_type IN ('paper_l2', 'paper_l3')",
            f"paper_id IN ({sql_in_list(paper_ids)})" if paper_ids else "1=1",
        ])
        code_where = " AND ".join([
            "chunk_type IN ('code_l2', 'code_l3')",
            f"paper_id IN ({sql_in_list(paper_ids)})" if paper_ids else "1=1",
        ])

        try:
            paper_results = table.search(query_emb).where(paper_where).limit(top_k_chunks // 2).to_list()
        except Exception:
            paper_results = table.search().where(paper_where).limit(top_k_chunks // 2).to_list()
        try:
            code_results = table.search(query_emb).where(code_where).limit(top_k_chunks // 2).to_list()
        except Exception:
            code_results = table.search().where(code_where).limit(top_k_chunks // 2).to_list()

        l2_results = paper_results + code_results

    # ---- Stage 3: Context expansion ----

    expanded = _expand_context(table, l2_results, intent, paper_scores)

    # ---- Stage 4: Re-rank and return ----

    # Sort by score descending
    expanded.sort(key=lambda r: r.score, reverse=True)

    # Cap at a reasonable context size (~4000 tokens worth of content)
    total_chars = 0
    capped: list[RetrievalResult] = []
    CHAR_BUDGET = 16000  # ~4000 tokens
    for r in expanded:
        if total_chars + len(r.content) > CHAR_BUDGET:
            break
        capped.append(r)
        total_chars += len(r.content)

    return capped, intent


def _expand_context(
    table: Any,
    l2_results: list[dict],
    intent: SearchIntent,
    paper_scores: dict[str, float],
) -> list[RetrievalResult]:
    """Stage 3: expand each L2 hit with L3 paragraphs + special blocks + call chain."""
    expanded: list[RetrievalResult] = []
    seen_ids: set[str] = set()

    for i, l2_row in enumerate(l2_results):
        l2_id = l2_row["chunk_id"]
        paper_id = l2_row["paper_id"]
        score = paper_scores.get(paper_id, 0.5) * (1.0 - i / max(len(l2_results), 1))

        # Add the L2 chunk itself
        if l2_id not in seen_ids:
            expanded.append(_row_to_result(l2_row, score))
            seen_ids.add(l2_id)

        chunk_type = l2_row.get("chunk_type", "")

        if chunk_type.startswith("paper_"):
            # ---- Paper context expansion ----

            # Downward: fetch related L3 paragraphs
            section_path = l2_row.get("section_path", "")
            try:
                l3_rows = (
                    table.search()
                    .where(f"paper_id = {sql_str(paper_id)} AND chunk_type = 'paper_l3'")
                    .limit(20)
                    .to_list()
                )
                # Filter L3 rows that are roughly within the same section
                l2_heading = section_path.split(" > ")[0] if section_path else ""
                for l3_row in l3_rows:
                    l3_path = l3_row.get("section_path", "")
                    if (l3_id := l3_row["chunk_id"]) not in seen_ids:
                        expanded.append(_row_to_result(l3_row, score * 0.9))
                        seen_ids.add(l3_id)
                        if len([r for r in expanded if r.chunk_type == "paper_l3" and r.paper_id == paper_id]) >= 5:
                            break
            except Exception:
                pass

            # Lateral: figures and tables (priority based on sub_type)
            if intent.sub_type in ("figure_lookup", "general"):
                try:
                    fig_rows = (
                        table.search()
                        .where(f"paper_id = {sql_str(paper_id)} AND chunk_type = 'figure'")
                        .limit(3)
                        .to_list()
                    )
                    for fig_row in fig_rows:
                        if (fid := fig_row["chunk_id"]) not in seen_ids:
                            expanded.append(_row_to_result(fig_row, score * 0.85))
                            seen_ids.add(fid)
                except Exception:
                    pass

            if intent.sub_type in ("benchmark", "general"):
                try:
                    tbl_rows = (
                        table.search()
                        .where(f"paper_id = {sql_str(paper_id)} AND chunk_type = 'table'")
                        .limit(3)
                        .to_list()
                    )
                    for tbl_row in tbl_rows:
                        if (tid := tbl_row["chunk_id"]) not in seen_ids:
                            expanded.append(_row_to_result(tbl_row, score * 0.85))
                            seen_ids.add(tid)
                except Exception:
                    pass

        elif chunk_type.startswith("code_"):
            # ---- Code context expansion ----

            # Downward: fetch L3/L4 siblings from the same file
            file_path = l2_row.get("file_path", "")
            repo = l2_row.get("repo_name", "")
            if file_path and repo:
                try:
                    siblings = (
                        table.search()
                        .where(
                            f"paper_id = {sql_str(paper_id)} AND repo_name = {sql_str(repo)} "
                            f"AND file_path = {sql_str(file_path)} AND chunk_type IN ('code_l3', 'code_l4')"
                        )
                        .limit(15)
                        .to_list()
                    )
                    for sib in siblings:
                        if (sid := sib["chunk_id"]) not in seen_ids:
                            expanded.append(_row_to_result(sib, score * 0.9))
                            seen_ids.add(sid)
                except Exception:
                    pass

            # Call chain: follow calls[] (one hop)
            calls = l2_row.get("calls") or []
            for call_id in calls[:5]:
                if call_id in seen_ids:
                    continue
                try:
                    call_rows = (
                        table.search()
                        .where(f"chunk_id = {sql_str(call_id)}")
                        .limit(1)
                        .to_list()
                    )
                    if call_rows:
                        expanded.append(_row_to_result(call_rows[0], score * 0.8))
                        seen_ids.add(call_id)
                except Exception:
                    pass

            # Fetch associated test
            test_id = l2_row.get("associated_test")
            if test_id and test_id not in seen_ids:
                try:
                    test_rows = (
                        table.search()
                        .where(f"chunk_id = {sql_str(test_id)}")
                        .limit(1)
                        .to_list()
                    )
                    if test_rows:
                        expanded.append(_row_to_result(test_rows[0], score * 0.75))
                        seen_ids.add(test_id)
                except Exception:
                    pass

    return expanded


# ---------------------------------------------------------------------------
# Convenience functions for specific retrieval patterns
# ---------------------------------------------------------------------------


def search_papers(
    query: str,
    top_k: int = 10,
    year_min: int | None = None,
    year_max: int | None = None,
    venue: str | None = None,
) -> tuple[list[RetrievalResult], SearchIntent]:
    """Convenience wrapper for paper-only search."""
    intent = SearchIntent(intent="paper_search", sub_type="general")
    return search(
        query=query,
        intent=intent,
        top_k_papers=20,
        top_k_chunks=top_k,
        year_min=year_min,
        year_max=year_max,
        venue=venue,
    )


def search_code(
    query: str,
    top_k: int = 10,
    repo_name: str | None = None,
) -> tuple[list[RetrievalResult], SearchIntent]:
    """Convenience wrapper for code-only search."""
    intent = SearchIntent(intent="code_search", sub_type="general")
    return search(
        query=query,
        intent=intent,
        top_k_papers=20,
        top_k_chunks=top_k,
    )


def get_chunk_by_id(
    chunk_id: str,
    db: lancedb.DBConnection | None = None,
) -> RetrievalResult | None:
    """Look up a single chunk by ID.

    Args:
        chunk_id: The chunk ID to look up.
        db: Optional LanceDB connection.

    Returns:
        RetrievalResult or None if not found.
    """
    if db is None:
        db = get_connection()
    table = init_chunks(db)

    try:
        rows = table.search().where(f"chunk_id = {sql_str(chunk_id)}").limit(1).to_list()
    except Exception:
        return None

    if not rows:
        return None

    return _row_to_result(rows[0], 1.0)


def get_paper_overview(paper_id: str, db: lancedb.DBConnection | None = None) -> dict[str, Any] | None:
    """Get a paper's overview: L1 abstract + section list + figure/table lists.

    Args:
        paper_id: The paper ID.
        db: Optional LanceDB connection.

    Returns:
        Overview dict or None if paper not found.
    """
    if db is None:
        db = get_connection()
    table = init_chunks(db)

    try:
        pid = sql_str(paper_id)
        # L1
        l1_rows = table.search().where(f"paper_id = {pid} AND chunk_type = 'paper_l1'").limit(1).to_list()
        # L2 sections
        l2_rows = table.search().where(f"paper_id = {pid} AND chunk_type = 'paper_l2'").to_list()
        # Figures
        fig_rows = table.search().where(f"paper_id = {pid} AND chunk_type = 'figure'").to_list()
        # Tables
        tbl_rows = table.search().where(f"paper_id = {pid} AND chunk_type = 'table'").to_list()
    except Exception:
        return None

    if not l1_rows:
        return None

    l1 = l1_rows[0]
    return {
        "paper_id": paper_id,
        "title": l1.get("title", ""),
        "authors": l1.get("authors", []),
        "year": l1.get("year"),
        "venue": l1.get("venue", ""),
        "arxiv_id": l1.get("arxiv_id"),
        "doi": l1.get("doi"),
        "abstract": l1.get("content", ""),
        "sections": [
            {"heading": r.get("section_path", ""), "chunk_id": r["chunk_id"]}
            for r in l2_rows
        ],
        "figures": [
            {"index": r.get("figure_index"), "caption": r.get("content", ""), "chunk_id": r["chunk_id"]}
            for r in fig_rows
        ],
        "tables": [
            {"index": r.get("table_dims"), "caption": r.get("content", ""), "chunk_id": r["chunk_id"]}
            for r in tbl_rows
        ],
    }
