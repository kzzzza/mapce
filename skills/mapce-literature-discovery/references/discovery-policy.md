# Discovery Policy

Use two passes. The first pass gathers roughly 20–30 metadata records per focused
query. The second pass selects a smaller set for full-text reading in MAPCE.

Source roles:

- MAPCE: indexed full text and code, suitable for evidence localization.
- arXiv: current CS and engineering preprints with an indexable identifier.
- OpenAlex: broader scholarly coverage, DOI links, and open-access locations.
- Crossref: DOI and bibliographic metadata checking, not full-text evidence.

Identity precedence is DOI, arXiv ID, then normalized title and publication year.
Normalize DOI prefixes and resolver URLs. Strip arXiv version suffixes. Normalize a
title with Unicode case folding, punctuation removal, and whitespace collapse.

Do not equate citation count with quality or relevance. Do not claim complete
coverage when an API failed, a source was omitted, or the query language was narrow.
Never bypass authentication or a paywall.
