---
name: mapce-scientific-writing
description: Draft, revise, and audit scientific reviews or research papers with MAPCE evidence provenance. Use for abstracts, introductions, related work, methods, results, discussions, IEEE/ACM manuscripts, BibTeX, response-to-reviewer work, or any LaTeX writing and revision such as “写论文”, “把调研整理成 LaTeX”, “检查引用和主张”, and “按 IEEE/ACM 投稿”. Require evidence locators, compile and layout gates for every LaTeX change, and visual approval before final PDF delivery.
license: MIT
compatibility: Requires MAPCE MCP and a MAPCE research workspace. LaTeX output requires latexmk, pdfinfo, pdftoppm, and an image-viewing tool.
metadata:
  version: "0.1.2"
---

# MAPCE Scientific Writing

Write from recorded evidence and research records. Fluent prose does not replace a
source, result, method, approval, or human decision.

## Intake

Obtain the document type, audience, target venue, stage, scope, approved workspace,
source manifest, evidence ledger, claims registry, methods, results, figures, tables,
and declarations. Mark missing fields rather than filling them with boilerplate.

Read `references/evidence-workflow.md`. For IEEE or ACM work, also read
`references/ieee-acm.md` and check the target venue's current official instructions.

## Build an evidence outline

For each planned section, list its purpose, claim IDs, evidence IDs, method/result
records, uncertainty, conflicting evidence, and unresolved information. Use MAPCE
`read_paper_section` to confirm context when a retrieved chunk is ambiguous.

Every factual or numeric literature claim maps to an evidence entry containing
`paper_id`, `chunk_id`, and `section_path`. Every manuscript citation key comes from
`get_paper_citation` or verified authoritative metadata. Never infer an author, DOI,
venue, result, method, page number, funding statement, ethics approval, or author role.

## Draft

Start from `assets/manuscript.md` and `assets/manuscript.tex`. Produce both formats and
one `references.bib` with matching keys. Preserve uncertainty, null results, failures,
deviations, alternative explanations, and concrete limitations.

Methods describe what was done. Results report recorded outcomes. Discussion interprets
those outcomes within the design's scope. Do not convert association to causation or
absence of significance to equivalence.

Keep `DRAFT — NOT FOR SUBMISSION` while any cited evidence lacks human verification or
while authorship, declarations, results, or venue checks remain unresolved.

## LaTeX quality gate

Read `references/latex-quality-gate.md` whenever LaTeX is generated or revised. Run the
bundled build command after every change. Compilation, unresolved references, and
overfull boxes larger than 2 pt are blocking failures.

Visual inspection of every rendered page is required for final delivery and whenever a
table, figure, or page count changes. After a visual failure, repair and recheck at most
twice. Leave the result pending for human review when the image-viewing tool is missing
or three visual inspections fail.

Do not call a PDF layout-approved, complete, final, or ready for delivery until the
corresponding `.layout-qa.json` says `status=layout_approved`. Generate a new approval
record after subsequent LaTeX or PDF changes. Layout approval does not remove the
scientific DRAFT state.

## Audit

Run the bundled audit from the workspace root:

```bash
python <skill-dir>/scripts/audit_workspace.py <workspace>
```

Resolve duplicate IDs, missing locators, undefined BibTeX keys, Markdown/LaTeX citation
mismatches, unresolved evidence markers, and an incorrectly removed draft banner.
Passing the script supports human review; it does not certify scientific correctness,
policy compliance, or submission readiness.

## Human approval

Only accountable human authors may mark evidence as `human_verified`, approve authors
and author order, approve declarations, remove the draft banner, or submit the paper.
Record AI use according to current venue policy.
