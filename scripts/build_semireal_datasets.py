#!/usr/bin/env python3
"""Build the two frozen UCI semireal confirmation datasets."""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repair_agent.semireal import (
    build_semireal_tasks,
    load_bike_source,
    load_wdbc_source,
    write_semireal_dataset,
)


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_all(source_dir: Path, out_root: Path, pairs=30, entities=12,
              downloaded_on="2026-10-24", tag="20261024", seed_base=2026102400):
    source_dir, out_root = Path(source_dir), Path(out_root)
    bike_archive = source_dir / "bike_sharing_275.zip"
    wdbc_archive = source_dir / "breast_cancer_diagnostic_17.zip"
    specs = {
        "bike": {
            "rows": load_bike_source(bike_archive), "key_fields": ["instant"],
            "seed": seed_base + 1, "archive": bike_archive,
            "out": out_root / f"semireal_bike_{tag}",
            "url": "https://archive.ics.uci.edu/static/public/275/bike%2Bsharing%2Bdataset.zip",
            "doi": "10.24432/C5W894",
        },
        "wdbc": {
            "rows": load_wdbc_source(wdbc_archive), "key_fields": ["ID"],
            "seed": seed_base + 2, "archive": wdbc_archive,
            "out": out_root / f"semireal_wdbc_{tag}",
            "url": "https://archive.ics.uci.edu/static/public/17/breast%2Bcancer%2Bwisconsin%2Bdiagnostic.zip",
            "doi": "10.24432/C5DW2B",
        },
    }
    outputs = {}
    for name, spec in specs.items():
        public, private, metadata = build_semireal_tasks(
            name, spec["rows"], spec["key_fields"], pairs=pairs,
            entities=entities, seed=spec["seed"], split="test",
        )
        source = {
            "url": spec["url"], "license": "CC BY 4.0", "doi": spec["doi"],
            "archive_sha256": _sha256(spec["archive"]),
            "archive_name": spec["archive"].name, "downloaded_on": downloaded_on,
        }
        write_semireal_dataset(spec["out"], public, private, metadata, source)
        outputs[name] = spec["out"]
    return outputs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, default=ROOT / "sources" / "uci")
    parser.add_argument("--out-root", type=Path, default=ROOT / "data")
    parser.add_argument("--pairs", type=int, default=30)
    parser.add_argument("--entities", type=int, default=12)
    parser.add_argument("--downloaded-on", default="2026-10-24")
    parser.add_argument("--tag", default="20261024")
    parser.add_argument("--seed-base", type=int, default=2026102400)
    args = parser.parse_args()
    outputs = build_all(
        args.source_dir, args.out_root, args.pairs, args.entities,
        args.downloaded_on, args.tag, args.seed_base,
    )
    for name, path in outputs.items():
        print(f"{name}={path}")


if __name__ == "__main__":
    main()
