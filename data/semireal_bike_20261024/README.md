# Semireal bike dataset

This dataset derives fixed-size clean subsets from a licensed public table and adds reproducible synthetic FD conflicts. The original retained source rows are the hidden truth; injected rows are not claimed to be naturally occurring errors.

- Source: https://archive.ics.uci.edu/static/public/275/bike%2Bsharing%2Bdataset.zip
- DOI: 10.24432/C5W894
- License: CC BY 4.0
- Downloaded: 2026-10-24
- Frozen archive: bike_sharing_275.zip
- Archive SHA-256: `b70182d0d0508e9abbb79306ce5c0cec34869000f8220175ac83d11dbe845401`
- FD basis: `instant -> all attributes`; the determinant is documented as an ID by the source repository.
- Public tasks: 60 from 30 paired base instances.

The public file excludes hidden truth. `private_truth.jsonl` is evaluation-only and must never be included in model prompts.
