---
name: mapce-paper-reading
description: Read and explain one or more indexed papers through MAPCE with section- and chunk-level evidence. Use for paper understanding, structured notes, concept or formula explanation, figure/table interpretation, method tracing, implementation guidance, reproduction checks, or questions such as “这篇论文讲了什么”, “解释图 3”, “方法如何实现”, and “论文与代码怎样对应”.
license: MIT
compatibility: Requires the MAPCE MCP server.
metadata:
  version: "0.1.0"
---

# MAPCE Paper Reading

Read papers from MAPCE without inventing content that is absent from the index.

## Resolve and inspect

1. Call `resolve_paper` with the internal ID, arXiv ID, or arXiv URL.
2. If it is not indexed, report that state and offer to use
   `mapce-literature-discovery`; do not pretend to have read the full text.
3. Call `get_paper_overview` for the abstract, outline, figures, tables, code status,
   and repository associations.
4. Call `get_paper_citation`. Use the returned citation key and metadata; never infer
   authors from a title.

## Plan evidence retrieval

Translate the user's question into a small set of evidence targets: definition,
method, assumptions, training, evaluation, findings, limitations, implementation,
or figure/table context.

Use `search_paper_content` to locate multiple relevant chunks inside the paper.
Use `read_paper_section` to read an exact section or continue around a chunk. Follow
pagination when the answer needs more context. Prefer the paper's wording and declared
scope over a generic explanation from memory.

## Figures and tables

Use the figure caption, surrounding section, table Markdown, and paper conclusions.
State whether the image itself was available for visual inspection. Do not infer axes,
values, visual relationships, or architectural details that are absent from the stored
caption and text.

## Code and reproduction

If `code_status=indexed`, call `search_code` with `paper_id` and, when appropriate,
`repo_url`. Link paper claims to exact files and symbols. Separate:

- information stated in the paper;
- behavior visible in indexed code or configuration;
- information still missing for reproduction.

When code is `no_code`, `needs_review`, `pending`, or `failed`, preserve that state.
Do not treat missing indexed code as proof that no implementation exists online.

## Write the note

Read `references/note-template.md`. Every factual or numeric note entry includes a
locator with `paper_id`, `chunk_id`, and `section_path`. A section path may be empty
for abstract-level evidence; a chunk ID may not be fabricated.

Use short quotations only when exact wording matters. Prefer a faithful paraphrase.
Mark unresolved questions and conflicts instead of filling gaps.
