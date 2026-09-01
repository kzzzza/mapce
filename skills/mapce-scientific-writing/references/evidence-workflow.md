# Evidence Workflow

Keep discovery, localization, authority checking, human verification, drafting, and
submission approval as separate states.

`source_manifest.json` stores bibliographic sources and their citation keys.
`evidence_ledger.csv` stores a bounded claim summary and MAPCE locator. `claims.csv`
stores a hash of each manuscript claim and the evidence IDs that support it.

Suggested draft markers:

```text
[claim:C001] [evidence:E001,E002]
```

A valid evidence row contains a real MAPCE `paper_id`, `chunk_id`, and the returned
`section_path`. If a result came from the abstract and MAPCE supplies no section path,
record `abstract` explicitly. Do not use a generated summary or another paper's
bibliography as verification.

Verification states:

- `stored_metadata_only`: citation fields came from the local index.
- `authority_checked`: bibliographic metadata was checked against an authority.
- `human_verified`: a person opened the source and confirmed claim support and locator.
- `missing`, `conflicting`, `retracted`: keep out of submission-ready claims.

Crossref can check DOI metadata but cannot verify that a paper supports a scientific
claim. Search snippets are screening aids. A model's prior knowledge is not evidence.
