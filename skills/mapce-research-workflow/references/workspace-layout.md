# Research Workspace Contract

The project workspace is separate from MAPCE's database and model cache.

```text
project.json
search/search_log.jsonl
papers/candidates.csv
papers/screening.csv
evidence/source_manifest.json
evidence/evidence_ledger.csv
evidence/claims.csv
notes/
design/
manuscript/review.md
manuscript/review.tex
manuscript/references.bib
cache/
build/
```

`project.json` records the question, output path, review mode, search cutoff,
current stage, indexing authorization, and unresolved decisions. Indexing authorization
is either project-scoped `autonomous` permission explicitly granted by the user or the
safe `per_paper` default. Raw API responses belong in `cache/`.
Files under `cache/` and `build/` are disposable; evidence registries are not.

The evidence locator is `paper_id + chunk_id + section_path`. Add a page number
only when a source provides a reliable printed page locator. MAPCE chunk order is
not a page number.

The source manifest uses these verification states:

- `stored_metadata_only`: exported from MAPCE without authority checking.
- `authority_checked`: bibliographic metadata checked against an authoritative source.
- `human_verified`: a person opened the source and confirmed support and locator.
- `conflicting`, `missing`, or `retracted`: requires explicit handling.

Only a human may promote a source or claim to `human_verified`.
