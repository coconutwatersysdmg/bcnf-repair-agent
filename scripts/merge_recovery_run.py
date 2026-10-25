"""Create an immutable derived run by overlaying targeted network-failure recovery rows."""
import argparse
import json
import shutil
from pathlib import Path


RECOVERABLE_STATUSES = {"NETWORK_ERROR", "REQUEST_UNCERTAIN"}


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line]


def _write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def merge_recovery_run(source_run, recovery_run, out_run, task_id, repeat):
    source = Path(source_run)
    recovery = Path(recovery_run)
    out = Path(out_run)
    if out.exists():
        raise FileExistsError("derived run directory already exists")

    source_rows = _read_jsonl(source / "results.jsonl")
    recovery_rows = _read_jsonl(recovery / "results.jsonl")
    source_keys = [(row["task_id"], row["arm"], row["repeat"]) for row in source_rows]
    recovery_keys = [(row["task_id"], row["arm"], row["repeat"]) for row in recovery_rows]
    if len(source_keys) != len(set(source_keys)) or len(recovery_keys) != len(set(recovery_keys)):
        raise ValueError("duplicate result keys")

    originals = {
        key: row for key, row in zip(source_keys, source_rows)
        if row["task_id"] == task_id and row["repeat"] == repeat
        and row.get("status") in RECOVERABLE_STATUSES
    }
    replacements = {
        key: row for key, row in zip(recovery_keys, recovery_rows)
        if row["task_id"] == task_id and row["repeat"] == repeat
    }
    if not originals:
        raise ValueError("no recoverable source rows for requested task/repeat")
    if set(replacements) != set(originals):
        raise ValueError("recovery rows do not exactly match recoverable source rows")
    for key, row in replacements.items():
        if row.get("task_hash") != originals[key].get("task_hash"):
            raise ValueError("recovery task hash differs from source")
    first_responses = []
    for row in replacements.values():
        trajectory = row.get("trajectory") or []
        response = trajectory[0].get("response") if trajectory else None
        if not isinstance(response, str):
            raise ValueError("recovery row lacks a first response")
        first_responses.append(response)
    if len(set(first_responses)) != 1:
        raise ValueError("recovery first responses are not paired")

    merged = []
    for key, row in zip(source_keys, source_rows):
        if key not in replacements:
            merged.append(row)
            continue
        replacement = dict(replacements[key])
        replacement["recovery_provenance"] = {
            "source_run": str(source),
            "recovery_run": str(recovery),
            "original_status": row["status"],
        }
        merged.append(replacement)

    source_manifest = _read_json(source / "manifest.json")
    source_summary = _read_json(source / "run_summary.json")
    recovery_summary = _read_json(recovery / "run_summary.json")
    source_cost = source_summary.get("ledger", {}).get("cost_cny", 0)
    recovery_cost = recovery_summary.get("ledger", {}).get("cost_cny", 0)
    overlay = {
        "derived": True,
        "source_run": str(source),
        "recovery_run": str(recovery),
        "task_id": task_id,
        "repeat": repeat,
        "replaced_rows": len(replacements),
        "replaced_arms": sorted(row["arm"] for row in replacements.values()),
        "original_statuses": {key[1]: originals[key]["status"] for key in sorted(originals)},
        "source_actual_cost_cny": source_cost,
        "actual_incremental_cost_cny": recovery_cost,
        "combined_actual_cost_cny": source_cost + recovery_cost,
    }
    source_manifest["derivation"] = overlay
    out.mkdir(parents=True)
    shutil.copyfile(source / "public_tasks.jsonl", out / "public_tasks.jsonl")
    _write_json(out / "manifest.json", source_manifest)
    (out / "results.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in merged),
        encoding="utf-8",
    )
    _write_json(out / "recovery_overlay.json", overlay)
    _write_json(out / "run_summary.json", {
        "completed": len(merged),
        "expected": len(source_rows),
        "mode": source_summary.get("mode"),
        "derived": True,
        "ledger": {
            "cost_cny": source_cost + recovery_cost,
            "source_cost_cny": source_cost,
            "recovery_cost_cny": recovery_cost,
        },
    })
    return overlay


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--recovery", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--repeat", required=True, type=int)
    args = parser.parse_args()
    result = merge_recovery_run(args.source, args.recovery, args.out, args.task_id, args.repeat)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
