---
name: mapce-literature-discovery
description: Discover papers for a research question using the local MAPCE corpus first, then arXiv, OpenAlex, and Crossref when broader coverage is needed. Use for “找相关论文”, “检索并筛选文献”, “查漏补缺”, “建立阅读清单”, citation chasing, or requests to add relevant papers to MAPCE. Always present a deduplicated candidate list and obtain user approval before indexing new papers.
license: MIT
compatibility: Requires MAPCE MCP; external discovery requires network access to public academic APIs.
metadata:
  version: "0.1.0"
---

# MAPCE Literature Discovery

Find relevant work while separating discovery metadata from verified full-text evidence.

## Scope the search

Record the research question, concepts, synonyms, exclusions, date range, venue or
field constraints, and search cutoff. Generate several focused queries instead of
one long natural-language query.

## Search local MAPCE first

Call `search_papers` for each major concept and combination. Use year and venue
filters when the user supplied them. Deduplicate results by `paper_id`, and record
which queries retrieved each paper.

For likely matches, call `get_paper_citation` to obtain stored identifiers. Treat
`verification_status=stored_metadata_only` as unverified metadata.

## Search external academic sources

Read `references/discovery-policy.md`. Use the bundled script for metadata discovery:

```bash
python scripts/discover_academic.py \
  --query "<focused query>" --limit 20 \
  --output <workspace>/papers/external-candidates.csv \
  --log <workspace>/search/search_log.jsonl
```

The script queries arXiv and OpenAlex, optionally checks a bounded number of DOI
records with Crossref, and deduplicates by DOI, arXiv ID, then normalized title/year.
Keep API errors in the search log; do not turn a failed source into an empty-coverage claim.

## Build the candidate list

Merge local and external candidates into `papers/candidates.csv`. For each row include:

- identifiers and bibliographic metadata;
- discovery source and exact query;
- relevance reason and intended evidence role;
- local status and full-text availability;
- an index source of `arxiv`, direct open PDF URL, or empty;
- decision and decision reason.

Metadata, abstracts, and search snippets support screening only. They do not support
manuscript claims.

## Approval gate

Present the shortlist before any write to MAPCE. Ask the user which candidates to index.
After approval:

- call `index_paper` with `source_type=arxiv` for an arXiv ID;
- call `index_paper` with `source_type=url` only for an accessible paper URL;
- submit one paper at a time;
- resolve each successful result and export its citation metadata.

Do not attempt to index a DOI resolver, abstract page, or paywalled page as if it were
a PDF. Leave non-indexable papers in the candidate list for bibliographic coverage.

## Coverage report

Report databases searched, exact queries, dates, counts, deduplication count,
screening decisions, indexing outcomes, and known coverage limitations.
