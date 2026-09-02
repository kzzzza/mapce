---
name: mapce-literature-discovery
description: Discover papers for a research question using the local MAPCE corpus first, then arXiv, OpenAlex, and Crossref when broader coverage is needed. Use for “找相关论文”, “检索并筛选文献”, “查漏补缺”, “建立阅读清单”, citation chasing, or requests to add relevant papers to MAPCE. Establish explicit project-scoped autonomous or per-paper indexing authorization before any MAPCE write.
license: MIT
compatibility: Requires MAPCE MCP; external discovery requires network access to public academic APIs.
metadata:
  version: "0.1.1"
---

# MAPCE Literature Discovery

Find relevant work while separating discovery metadata from verified full-text evidence.

## Establish indexing authorization

Before starting the search, ask whether the user grants project-scoped autonomous paper
indexing or wants to approve each paper. Record one of these modes in `project.json` when
a research workspace exists:

- `autonomous`: explicit permission to index relevant, screened, identity-verified,
  openly accessible papers for this project without another per-paper prompt;
- `per_paper`: the safe default; present each exact candidate and wait for approval.

An unanswered question, an unattended run, or a general instruction to continue never
counts as autonomous permission. Permission to search external services is separate from
permission to write to MAPCE. Do not reuse authorization from another project or session.

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

Present the shortlist before any write to MAPCE. Apply the recorded authorization mode:

- In `per_paper` mode, ask the user to approve the exact candidates before every
  `index_paper` call.
- In `autonomous` mode, state which screened candidates meet the recorded scope and may
  proceed without another prompt. Do not treat the mode as approval for all raw search
  results.

Before either mode writes, verify the candidate identity by matching the intended title
to its arXiv ID or DOI and check that `resolve_paper` does not already find it locally.
Never index a guessed identifier. After authorization and identity checks:

- call `index_paper` with `source_type=arxiv` for an arXiv ID;
- call `index_paper` with `source_type=url` only for an accessible paper URL;
- submit one paper at a time;
- resolve each successful result and export its citation metadata.

Record the authorization mode, candidate identity check, indexing outcome, and any
failure in the project files. A request to delete an indexed paper or index an associated
code repository requires its own authorization.

Do not attempt to index a DOI resolver, abstract page, or paywalled page as if it were
a PDF. Leave non-indexable papers in the candidate list for bibliographic coverage.

## Coverage report

Report databases searched, exact queries, dates, counts, deduplication count,
screening decisions, indexing outcomes, and known coverage limitations.
