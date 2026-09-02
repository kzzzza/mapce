---
name: mapce-research-workflow
description: Coordinate an end-to-end research project using MAPCE, from research scoping and literature discovery through paper reading, review, experimental design, and manuscript drafting. Use for broad requests such as “调研这个方向并形成论文”, “建立研究工作流”, “从文献到实验和写作”, or any task spanning two or more research stages. Route narrow single-stage requests to the matching MAPCE specialist skill instead.
license: MIT
compatibility: Requires the MAPCE MCP server and the complete MAPCE research skill bundle.
metadata:
  version: "0.1.2"
---

# MAPCE Research Workflow

Coordinate the research process while keeping MAPCE as the evidence service.
Do not open LanceDB, load embeddings, or write into `MAPCE_DATA_DIR` directly.

## Intake gates

Before writing files, establish:

1. The research question, intended audience, domain, time range, and deliverable.
2. The output directory. If the user did not provide one, ask whether to use
   `<current-working-directory>/research/<project-slug>/`.
3. For a review, ask whether to run a rapid review or a PRISMA-style review.
   Recommend rapid review for low-cost orientation.
4. Whether external academic search is allowed. Searching MAPCE itself remains local.
5. The indexing authorization for this project. Ask the user to choose one mode before
   discovery begins:
   - `autonomous`: the user explicitly authorizes the agent to index relevant,
     identity-verified, openly accessible papers for this project without asking again
     for each paper;
   - `per_paper`: every exact paper requires user approval before `index_paper`.

Indexing authorization is scoped to the current project and may be revoked at any time.
Do not infer `autonomous` authorization from instructions such as "continue", "finish
the research", "run unattended", or from permission to search external sources. If the
user does not answer, use `per_paper` and stop at the candidate approval gate before any
MAPCE write.

Do not create a workspace while either the output location or review mode is
unresolved. In a non-interactive automation that explicitly requests immediate
execution, use the proposed `research/<project-slug>/` path and rapid-review mode,
and record both defaults in `project.json`. This exception applies only to the output
path and review mode. It never grants permission to call `index_paper`.

## Initialize the workspace

Read `references/workspace-layout.md`, then run:

```bash
python scripts/init_workspace.py --output-dir <approved-path> \
  --title "<project title>" --question "<research question>" \
  --review-mode rapid --indexing-permission per-paper
```

The script refuses to overwrite an existing research workspace.
Use `--indexing-permission autonomous --user-authorized-autonomous-indexing` only
after the user explicitly grants project-scoped autonomous indexing. The workspace
initializer rejects an autonomous setting without that confirmation flag.

## Route the work

- Use `mapce-literature-discovery` to find local and external papers. Treat its indexing
  authorization gate as the single authority for all `index_paper` calls.
- Use `mapce-paper-reading` for evidence-grounded notes on selected papers.
- Use `mapce-literature-review` for thematic synthesis and review outputs.
- Use `mapce-experimental-design` before experiments or benchmark execution.
- Use `mapce-scientific-writing` for manuscript drafting and evidence audits.

Any stage that creates or revises LaTeX must use the scientific-writing LaTeX quality
gate. Do not treat a compiled PDF as a final deliverable without a current
`status=layout_approved` record from a complete rendered-page inspection.

Run indexing requests serially through MAPCE. Do not invoke a second MAPCE
service or direct Python database connection.

Before autonomous indexing, resolve or otherwise verify the candidate identity against
its title and arXiv ID or DOI. Autonomous authorization permits relevant screened papers;
it does not permit blind bulk ingestion, indexing a guessed identifier, deleting papers,
or indexing code repositories.

## State transitions

Update `project.json` after each completed stage using these states:

`scoped`, `discovery`, `screening`, `reading`, `synthesis`, `design`, `drafting`,
`human_review`, `complete`.

Never set `complete` while unresolved evidence, citations, or user decisions
remain. Keep generated manuscripts marked as drafts until a human verifies the
evidence and approves the document.

## Failure handling

- MAPCE unavailable: report the service error and stop evidence-dependent work.
- External source unavailable: record the source, time, query, and error, then
  continue with available sources if coverage remains adequate.
- Paper cannot be indexed: keep its metadata in `papers/candidates.csv`; do not
  claim full-text support.
- Conflicting evidence: preserve both positions and flag the conflict for review.
