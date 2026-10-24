"""Build paired BCNF tasks from licensed clean source tables plus fixed injections."""
from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import random
import zipfile
from pathlib import Path

from .data_builder import CATEGORIES
from .domain import canonical, task_hash, validate_task


BIKE_FIELDS = ("instant", "dteday", "season", "hr", "weathersit", "temp", "hum", "windspeed", "cnt")
WDBC_FIELDS = ("ID", "Diagnosis", "radius1", "texture1", "perimeter1", "area1",
               "smoothness1", "compactness1", "concavity1", "concave_points1")


def load_bike_source(path):
    with zipfile.ZipFile(path) as archive:
        text = archive.read("hour.csv").decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows = [{field: row[field] for field in BIKE_FIELDS} for row in reader]
    if len(rows) != 17379 or len({row["instant"] for row in rows}) != len(rows):
        raise ValueError("unexpected UCI Bike Sharing archive")
    return rows


def load_wdbc_source(path):
    with zipfile.ZipFile(path) as archive:
        text = archive.read("wdbc.data").decode("utf-8-sig")
    rows = []
    for values in csv.reader(io.StringIO(text)):
        if not values:
            continue
        if len(values) != 32:
            raise ValueError("unexpected WDBC row width")
        rows.append(dict(zip(WDBC_FIELDS, values[:len(WDBC_FIELDS)])))
    if len(rows) != 569 or len({row["ID"] for row in rows}) != len(rows):
        raise ValueError("unexpected UCI WDBC archive")
    return rows


def _base_id(domain_name, seed, index):
    return hashlib.sha256(f"semireal:{domain_name}:{seed}:{index}".encode()).hexdigest()[:20]


def build_semireal_tasks(domain_name, source_rows, key_fields, pairs=30,
                         entities=12, seed=2026102401, split="test"):
    if not isinstance(domain_name, str) or not domain_name:
        raise ValueError("invalid domain_name")
    if type(pairs) is not int or pairs < 1 or type(entities) is not int or entities < 4:
        raise ValueError("invalid pairs/entities")
    if not source_rows or len(source_rows) < entities:
        raise ValueError("insufficient source rows")
    attributes = list(source_rows[0])
    if not attributes or any(list(row) != attributes for row in source_rows):
        raise ValueError("source rows require one stable non-empty schema")
    if not key_fields or not set(key_fields) <= set(attributes):
        raise ValueError("invalid key fields")
    normalized = []
    for row in source_rows:
        values = {name: str(row[name]) for name in attributes}
        if any(value == "" for value in values.values()):
            raise ValueError("source rows must not contain empty values")
        normalized.append(values)
    keys = [tuple(row[name] for name in key_fields) for row in normalized]
    if len(keys) != len(set(keys)):
        raise ValueError("source key is not unique")
    non_keys = [name for name in attributes if name not in key_fields]
    if not non_keys:
        raise ValueError("source relation needs a non-key attribute")

    public, private = [], []
    for index in range(pairs):
        category = CATEGORIES[index % len(CATEGORIES)]
        base = _base_id(domain_name, seed, index)
        rng = random.Random(base)
        chosen = [copy.deepcopy(row) for row in rng.sample(normalized, entities)]
        labeled = [(row, True) for row in chosen]
        if category in {"residual", "mixed", "ambiguous"}:
            inject_count = max(3, entities // 2)
            for dirty_index in range(inject_count):
                row = copy.deepcopy(chosen[dirty_index % len(chosen)])
                field = non_keys[dirty_index % len(non_keys)]
                row[field] = f"{row[field]}__injected_{index}_{dirty_index}"
                labeled.append((row, False))
        else:
            inject_count = 0
        rng.shuffle(labeled)
        records, true_ids = [], []
        for position, (row, is_true) in enumerate(labeled):
            rid = "r" + hashlib.sha256(f"{base}:row:{position}".encode()).hexdigest()[:16]
            records.append({"id": rid, "values": [row[name] for name in attributes]})
            if is_true:
                true_ids.append(rid)
        true_ids = sorted(true_ids)
        all_ids = sorted(record["id"] for record in records)
        if category == "clean":
            initial = true_ids[:]
        elif category == "over_deletion":
            initial = true_ids[:-1]
        elif category == "mixed":
            initial = sorted(set(all_ids) - {true_ids[-1]})
        else:
            initial = all_ids
        evidence_rng = random.Random(hashlib.sha256(f"{base}:evidence".encode()).hexdigest())
        evidence = {}
        true_set = set(true_ids)
        for record in records:
            is_true = record["id"] in true_set
            score = evidence_rng.uniform(.38, .92) if is_true else evidence_rng.uniform(.25, .86)
            if category == "ambiguous":
                score = evidence_rng.uniform(.32, .88)
            evidence[record["id"]] = {
                "source": f"source_{evidence_rng.randrange(4)}",
                "score": round(score, 3),
            }
        schema = {
            "name": f"Semireal_{domain_name}_{base[:6]}",
            "attributes": attributes,
            "fds": [{"lhs": list(key_fields), "rhs": attributes}],
        }
        for track in ("C0", "C1"):
            task = {
                "task_id": f"t_{base}_{track}", "base_instance_id": base,
                "split": split, "schema": copy.deepcopy(schema),
                "records": copy.deepcopy(records), "initial_keep_ids": initial[:],
                "source_evidence": {} if track == "C0" else copy.deepcopy(evidence),
                "category": category, "family": f"semireal_{domain_name}", "track": track,
            }
            validate_task(task)
            public.append(task)
            private.append({
                "task_id": task["task_id"], "base_instance_id": base,
                "true_ids": true_ids[:], "task_hash": task_hash(task),
                "injection_count": inject_count,
            })
    metadata = {
        "version": 1, "domain": domain_name, "seed": seed, "split": split,
        "base_instances": pairs, "count": len(public), "entities": entities,
        "source_row_count": len(source_rows), "attributes": attributes,
        "key_fields": list(key_fields),
        "category_counts": {category: sum(t["category"] == category for t in public) for category in CATEGORIES},
    }
    return public, private, metadata


def write_semireal_dataset(path, public, private, metadata, source):
    path = Path(path)
    if path.exists():
        raise FileExistsError("dataset directory already exists; choose a new path")
    required = {"url", "license", "doi", "archive_sha256", "archive_name", "downloaded_on"}
    if set(source) != required:
        raise ValueError("incomplete source provenance")
    path.mkdir(parents=True)
    for name, rows in (("public.jsonl", public), ("private_truth.jsonl", private)):
        (path / name).write_text("".join(canonical(row) + "\n" for row in rows), encoding="utf-8")
    manifest = copy.deepcopy(metadata)
    manifest["source"] = copy.deepcopy(source)
    manifest["hashes"] = {
        name: hashlib.sha256((path / name).read_bytes()).hexdigest()
        for name in ("public.jsonl", "private_truth.jsonl")
    }
    (path / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    readme = f"""# Semireal {metadata['domain']} dataset

This dataset derives fixed-size clean subsets from a licensed public table and adds reproducible synthetic FD conflicts. The original retained source rows are the hidden truth; injected rows are not claimed to be naturally occurring errors.

- Source: {source['url']}
- DOI: {source['doi']}
- License: {source['license']}
- Downloaded: {source['downloaded_on']}
- Frozen archive: {source['archive_name']}
- Archive SHA-256: `{source['archive_sha256']}`
- FD basis: `{','.join(metadata['key_fields'])} -> all attributes`; the determinant is documented as an ID by the source repository.
- Public tasks: {metadata['count']} from {metadata['base_instances']} paired base instances.

The public file excludes hidden truth. `private_truth.jsonl` is evaluation-only and must never be included in model prompts.
"""
    (path / "README.md").write_text(readme, encoding="utf-8")
    return manifest
