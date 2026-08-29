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
from mapce.core.vector_index import configure_vector_query, has_vector_index
from mapce.db import get_connection, get_meta, init_chunks, init_index_meta, sql_in_list, sql_str


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class VectorSearchError(RuntimeError):
    """Raised when LanceDB vector search fails and no safe result exists."""


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
    repo_url: str | None = None
    file_path: str | None = None
    language: str | None = None
    code_content: str | None = None
    calls: list[str] = field(default_factory=list)
    called_by: list[str] = field(default_factory=list)

    # Special fields
    figure_path: str | None = None
    table_markdown: str | None = None
    config_keys: list[str] = field(default_factory=list)


# Never copy the 1024-float embedding back into Python result dictionaries.
# ``_distance`` is explicitly projected for vector searches; LanceDB currently
# auto-projects it, but making it explicit keeps behavior stable across SDK
# versions.
_RESULT_COLUMNS = [
    "chunk_id", "chunk_type", "paper_id", "title", "authors", "year",
    "venue", "section_path", "content", "repo_name", "repo_url",
    "file_path", "language", "calls", "called_by", "associated_test",
    "figure_path", "table_markdown", "config_keys",
]
_VECTOR_RESULT_COLUMNS = [*_RESULT_COLUMNS, "_distance"]


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
        repo_url=row.get("repo_url"),
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
    repo_name: str | None = None,
    paper_id: str | None = None,
    repo_url: str | None = None,
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
        repo_name: Optional repository-name filter for code results.
        paper_id: Optional owning-paper filter for code results.
        repo_url: Optional normalized repository URL filter for code results.

    Returns:
        (expanded_results, intent) tuple.

    Raises:
        VectorSearchError: If LanceDB cannot execute a vector search. No
            unranked fallback rows are returned in this case.
    """
    if db is None:
        db = get_connection()

    if intent is None:
        intent = parse_intent(query)

    # Explicit API arguments take precedence over filters inferred by an intent
    # parser. Convenience wrappers pass an explicit SearchIntent, so this merge
    # must happen independently of intent construction.
    if year_min is not None:
        intent.filters["year_min"] = year_min
    if year_max is not None:
        intent.filters["year_max"] = year_max
    if venue is not None:
        intent.filters["venue"] = venue

    if top_k_chunks <= 0:
        return [], intent

    table = init_chunks(db)
    vector_indexed = has_vector_index(table)

    # ---- Stage 1+2: Two-signal retrieval over the full corpus ----
    #
    # The previous design screened candidate papers by L1-abstract similarity
    # (top_k_papers) and then searched L2/L3 *only within those papers*. On a
    # homogeneous corpus that funnel dropped ~43% of deep paragraphs whose paper
    # abstract didn't match the query, capping fine-grained recall (R3/R4).
    #
    # We instead combine two ungated signals and fuse them:
    #   (a) L1 prior  — abstract-level similarity across ALL papers. Keeps
    #       title/abstract (known-item) queries strong: the title lives only in
    #       L1, so this is what lets a paper's own title find it.
    #   (b) Fine hits — direct L2/L3 vector search across ALL papers, so deep
    #       paragraphs are reachable regardless of how well the abstract matched.
    # The candidate set seeds from both; each paper's prior is max(L1, fine) so a
    # paper wins if *either* its abstract or any of its paragraphs matches.
    # year/venue filters move down onto the chunk query (base fields propagate
    # to every paper chunk).

    query_emb = embed_single(query)

    def _vsearch(where: str, limit: int) -> list[dict]:
        try:
            vector_query = (
                table.search(query_emb)
                .where(where, prefilter=True)
                .select(_VECTOR_RESULT_COLUMNS)
                .limit(limit)
            )
            vector_query = configure_vector_query(
                vector_query, indexed=vector_indexed
            )
            return vector_query.to_list()
        except Exception as exc:
            raise VectorSearchError(
                "Vector search failed; no fallback results were returned."
            ) from exc

    # Paper prior = best chunk similarity + a light L1 "known-item anchor".
    #
    #   prior(p) = max_chunk 1/(1+distance)            # how close the *best*
    #                                                  #   matching chunk of p is
    #            + L1_ANCHOR_W / (L1_ANCHOR_K + rank)  # bonus if p's abstract is
    #                                                  #   a top L1 match
    #
    # The similarity term lets an exact/near paragraph match win deep queries
    # (the title is not in any paragraph, so a topic-diluted abstract can't beat
    # it). The small anchor term only decides near-ties — precisely the
    # known-item/title case, where the answer's abstract tops the L1 list but its
    # similarity is a hair behind some distractor paragraph. This combination
    # keeps title→paper recall high *and* makes deep paragraphs reachable, which
    # pure distance fusion or pure RRF each sacrifice one of. (Swept empirically.)
    L1_ANCHOR_W = 2.0
    L1_ANCHOR_K = 60

    def _best_sim(rows: list[dict]) -> dict[str, float]:
        """Max similarity (1/(1+distance)) per paper_id across the given rows."""
        sims: dict[str, float] = {}
        for i, r in enumerate(rows):
            pid = r.get("paper_id")
            if not pid:
                continue
            dist = r.get("_distance")
            v = 1.0 / (1.0 + dist) if dist is not None else 1.0 / (1.0 + i)
            if pid not in sims or v > sims[pid]:
                sims[pid] = v
        return sims

    def _l1_anchor(l1_rows: list[dict]) -> dict[str, float]:
        """First-occurrence anchor bonus per paper_id from the L1 ranked list."""
        anchor: dict[str, float] = {}
        for i, r in enumerate(l1_rows):
            pid = r.get("paper_id")
            if pid and pid not in anchor:
                anchor[pid] = L1_ANCHOR_W / (L1_ANCHOR_K + i)
        return anchor

    paper_filter = ""
    if intent.filters.get("year_min"):
        paper_filter += f" AND year >= {intent.filters['year_min']}"
    if intent.filters.get("year_max"):
        paper_filter += f" AND year <= {intent.filters['year_max']}"
    if intent.filters.get("venue"):
        paper_filter += f" AND venue = {sql_str(intent.filters['venue'])}"

    # Wider pool than top_k_chunks since hits span L2 and L3 granularities.
    paper_limit = top_k_chunks * 3

    if intent.intent == "code_search":
        # Code queries don't benefit from the L1 (paper abstract) anchor; rank by
        # best code-chunk similarity over the whole corpus.
        code_filter = "chunk_type IN ('code_l2', 'code_l3')"
        if repo_name is not None:
            code_filter += f" AND repo_name = {sql_str(repo_name)}"
        if paper_id is not None:
            code_filter += f" AND paper_id = {sql_str(paper_id)}"
        if repo_url is not None:
            if paper_id is not None:
                # Historical chunks may predate repo_url propagation. The MCP
                # layer validates that this URL belongs to the paper first.
                code_filter += f" AND (repo_url = {sql_str(repo_url)} OR repo_url IS NULL)"
            else:
                code_filter += f" AND repo_url = {sql_str(repo_url)}"
        l2_results = _vsearch(code_filter, paper_limit)
        paper_scores = _best_sim(l2_results)
    else:
        # (a) L1 abstract list + (b) fine L2/L3 hits, both across all papers.
        l1_hits = _vsearch("chunk_type = 'paper_l1'" + paper_filter, top_k_papers * 100)
        fine_hits = _vsearch(
            "chunk_type IN ('paper_l2', 'paper_l3')" + paper_filter, paper_limit
        )
        # Candidate set = fine paragraph hits + the top L1 papers as known-item
        # anchors. _expand_context dedups by chunk_id; ordering comes from the
        # fused prior below, not list position.
        seed_l1 = l1_hits[:top_k_chunks]
        sim_rows = l1_hits + fine_hits
        if intent.intent == "hybrid":
            code_filter = "chunk_type IN ('code_l2', 'code_l3')"
            if repo_name is not None:
                code_filter += f" AND repo_name = {sql_str(repo_name)}"
            if paper_id is not None:
                code_filter += f" AND paper_id = {sql_str(paper_id)}"
            if repo_url is not None:
                if paper_id is not None:
                    code_filter += f" AND (repo_url = {sql_str(repo_url)} OR repo_url IS NULL)"
                else:
                    code_filter += f" AND repo_url = {sql_str(repo_url)}"
            code_hits = _vsearch(code_filter, top_k_chunks)
            sim_rows = sim_rows + code_hits
            l2_results = fine_hits + code_hits + seed_l1
        else:
            l2_results = fine_hits + seed_l1

        sims = _best_sim(sim_rows)
        anchor = _l1_anchor(l1_hits)
        paper_scores = {
            pid: sims.get(pid, 0.0) + anchor.get(pid, 0.0)
            for pid in set(sims) | set(anchor)
        }

    # Order candidates by fused paper prior so _expand_context's positional
    # weighting aligns with relevance (a paper with a strong fine hit floats to
    # the front regardless of whether it was an L1 seed or a deep paragraph).
    l2_results.sort(key=lambda r: paper_scores.get(r.get("paper_id"), 0.0), reverse=True)

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
        if len(capped) >= top_k_chunks:
            break
        if total_chars + len(r.content) > CHAR_BUDGET:
            continue
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
                    .where(
                        f"paper_id = {sql_str(paper_id)} AND chunk_type = 'paper_l3'",
                        prefilter=True,
                    )
                    .select(_RESULT_COLUMNS)
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
                        .where(
                            f"paper_id = {sql_str(paper_id)} AND chunk_type = 'figure'",
                            prefilter=True,
                        )
                        .select(_RESULT_COLUMNS)
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
                        .where(
                            f"paper_id = {sql_str(paper_id)} AND chunk_type = 'table'",
                            prefilter=True,
                        )
                        .select(_RESULT_COLUMNS)
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
            repo_url = l2_row.get("repo_url")
            if file_path and repo:
                try:
                    siblings = (
                        table.search()
                        .where(
                            f"paper_id = {sql_str(paper_id)} AND repo_name = {sql_str(repo)} "
                            + (f"AND repo_url = {sql_str(repo_url)} " if repo_url else "")
                            + f"AND file_path = {sql_str(file_path)} AND chunk_type IN ('code_l3', 'code_l4')",
                            prefilter=True,
                        )
                        .select(_RESULT_COLUMNS)
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
                        .where(f"chunk_id = {sql_str(call_id)}", prefilter=True)
                        .select(_RESULT_COLUMNS)
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
                        .where(f"chunk_id = {sql_str(test_id)}", prefilter=True)
                        .select(_RESULT_COLUMNS)
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
    paper_id: str | None = None,
    repo_url: str | None = None,
) -> tuple[list[RetrievalResult], SearchIntent]:
    """Convenience wrapper for code-only search."""
    intent = SearchIntent(intent="code_search", sub_type="general")
    return search(
        query=query,
        intent=intent,
        top_k_papers=20,
        top_k_chunks=top_k,
        repo_name=repo_name,
        paper_id=paper_id,
        repo_url=repo_url,
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
    from mapce.core.code_repositories import get_repository_associations
    meta = get_meta(init_index_meta(db), paper_id)
    repositories = get_repository_associations(paper_id, db)

    return {
        "paper_id": paper_id,
        "title": l1.get("title", ""),
        "authors": l1.get("authors", []),
        "year": l1.get("year"),
        "venue": l1.get("venue", ""),
        "arxiv_id": l1.get("arxiv_id"),
        "doi": l1.get("doi"),
        "code_status": (meta or {}).get(
            "code_status",
            "indexed" if (meta or {}).get("code_indexed") else "not_checked",
        ),
        "code_repositories": repositories,
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
