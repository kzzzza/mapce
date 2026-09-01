---
name: mapce-literature-review
description: Produce an evidence-traceable rapid, scoping, or PRISMA-style literature review using MAPCE papers and approved external discovery. Use for literature reviews, surveys, related-work synthesis, method comparisons, historical development, trend analysis, research-gap analysis, “论文综述”, “相关工作”, or “这个方向的发展历史”. Ask for the review mode before starting and organize synthesis by themes rather than paper-by-paper summaries.
license: MIT
compatibility: Requires MAPCE MCP and the complete MAPCE research skill bundle.
metadata:
  version: "0.1.0"
---

# MAPCE Literature Review

Create a reproducible synthesis whose claims can be traced to indexed paper content.

## Select the review mode

Before discovery or writing, ask the user to choose:

- `rapid`: low-cost orientation with recorded queries, explicit selection, and
  evidence-backed thematic synthesis;
- `prisma`: protocol-driven search and screening with stage counts, exclusion reasons,
  quality assessment, and a PRISMA-style flow record.

Recommend rapid mode unless the user needs publication-grade systematic review
methods. If an explicit non-interactive instruction says to proceed without questions,
use rapid mode and record the default.

Read `references/review-modes.md` after selecting the mode.

## Discover and screen

Use `mapce-literature-discovery`. Search local MAPCE first, then approved external
sources. Do not index external papers until the user approves the candidate list.

Define inclusion and exclusion criteria before full-text screening. Record search
queries, sources, dates, result counts, duplicates, decisions, and reasons. Abstracts
may support initial screening but not final evidence claims.

## Extract evidence

For every included paper:

1. Use `mapce-paper-reading` to retrieve citation metadata and relevant chunks.
2. Record study purpose, assumptions, method, datasets or tasks, metrics, main
   findings, limitations, and evidence locators.
3. Record contradictions and missing information without reconciling them by guesswork.
4. Treat preprints, peer-reviewed versions, surveys, and primary studies as distinct
   publication states.

## Synthesize

Organize the review by research question, method family, evidence theme, or development
stage. Compare approaches on dimensions supported by the included evidence. A history
section may be chronological, but the analysis still explains changes in assumptions,
methods, evaluation, and remaining gaps.

Avoid a sequence of isolated paper summaries. Report uncertainty, negative findings,
conflicting evidence, corpus limits, and search cutoff.

## Outputs

Start from `assets/review.md` and `assets/review.tex`. Produce both formats plus
`references.bib`; use identical citation keys. In PRISMA mode also produce a protocol,
screening table, exclusion summary, quality assessment, and flow counts.

Keep `DRAFT — NOT FOR SUBMISSION` until a human checks every included source and
approves the synthesis. Do not claim PRISMA compliance merely because files exist.
