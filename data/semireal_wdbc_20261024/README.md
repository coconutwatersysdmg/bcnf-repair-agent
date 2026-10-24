# Semireal wdbc dataset

This dataset derives fixed-size clean subsets from a licensed public table and adds reproducible synthetic FD conflicts. The original retained source rows are the hidden truth; injected rows are not claimed to be naturally occurring errors.

- Source: https://archive.ics.uci.edu/static/public/17/breast%2Bcancer%2Bwisconsin%2Bdiagnostic.zip
- DOI: 10.24432/C5DW2B
- License: CC BY 4.0
- Downloaded: 2026-10-24
- Frozen archive: breast_cancer_diagnostic_17.zip
- Archive SHA-256: `bc154869ef13f753f9e2b5a17e248cfe1ba4b6721db7c4da9f4880e40b05d3af`
- FD basis: `ID -> all attributes`; the determinant is documented as an ID by the source repository.
- Public tasks: 60 from 30 paired base instances.

The public file excludes hidden truth. `private_truth.jsonl` is evaluation-only and must never be included in model prompts.
