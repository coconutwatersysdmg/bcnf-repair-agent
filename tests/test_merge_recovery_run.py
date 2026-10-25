import json
import tempfile
import unittest
from pathlib import Path

from scripts.merge_recovery_run import merge_recovery_run


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


class MergeRecoveryRunTests(unittest.TestCase):
    def test_replaces_only_uncertain_rows_and_records_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            recovery = root / "recovery"
            out = root / "derived"
            source.mkdir()
            recovery.mkdir()
            task = "task_C1"
            public = '{"task_id":"task_C1"}\n'
            (source / "public_tasks.jsonl").write_text(public, encoding="utf-8")
            (source / "manifest.json").write_text(
                json.dumps({"arms": ["D0", "B0", "B1"], "repeats": 2}), encoding="utf-8"
            )
            (source / "run_summary.json").write_text(
                json.dumps({"ledger": {"cost_cny": 1.0}}), encoding="utf-8"
            )
            (recovery / "run_summary.json").write_text(
                json.dumps({"ledger": {"cost_cny": 0.02}}), encoding="utf-8"
            )
            source_rows = [
                {"task_id": task, "task_hash": "h", "arm": "D0", "repeat": 1, "status": "PASS", "trajectory": []},
                {"task_id": task, "task_hash": "h", "arm": "B0", "repeat": 1, "status": "NETWORK_ERROR", "trajectory": []},
                {"task_id": task, "task_hash": "h", "arm": "B1", "repeat": 1, "status": "REQUEST_UNCERTAIN", "trajectory": []},
            ]
            recovery_rows = [
                {"task_id": task, "task_hash": "h", "arm": arm, "repeat": 1, "status": "PASS",
                 "trajectory": [{"response": "paired"}]}
                for arm in ("B0", "B1")
            ]
            write_jsonl(source / "results.jsonl", source_rows)
            write_jsonl(recovery / "results.jsonl", recovery_rows)

            summary = merge_recovery_run(source, recovery, out, task, 1)

            merged = [json.loads(line) for line in (out / "results.jsonl").read_text().splitlines()]
            self.assertEqual(len(merged), 3)
            self.assertEqual(merged[0]["arm"], "D0")
            self.assertNotIn("recovery_provenance", merged[0])
            self.assertEqual({row["arm"] for row in merged[1:]}, {"B0", "B1"})
            self.assertTrue(all(row["recovery_provenance"]["original_status"] in
                                {"NETWORK_ERROR", "REQUEST_UNCERTAIN"} for row in merged[1:]))
            self.assertEqual(summary["replaced_rows"], 2)
            self.assertEqual(summary["actual_incremental_cost_cny"], 0.02)
            self.assertEqual((out / "public_tasks.jsonl").read_text(), public)

    def test_refuses_unpaired_recovery_first_responses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            recovery = root / "recovery"
            source.mkdir()
            recovery.mkdir()
            for run in (source, recovery):
                (run / "run_summary.json").write_text(json.dumps({"ledger": {"cost_cny": 0}}))
            (source / "manifest.json").write_text(json.dumps({"arms": ["B0", "B1"], "repeats": 1}))
            (source / "public_tasks.jsonl").write_text("{}\n")
            write_jsonl(source / "results.jsonl", [
                {"task_id": "t", "task_hash": "h", "arm": arm, "repeat": 0,
                 "status": "REQUEST_UNCERTAIN", "trajectory": []}
                for arm in ("B0", "B1")
            ])
            write_jsonl(recovery / "results.jsonl", [
                {"task_id": "t", "task_hash": "h", "arm": arm, "repeat": 0,
                 "status": "PASS", "trajectory": [{"response": response}]}
                for arm, response in (("B0", "one"), ("B1", "two"))
            ])

            with self.assertRaisesRegex(ValueError, "first responses"):
                merge_recovery_run(source, recovery, root / "out", "t", 0)


if __name__ == "__main__":
    unittest.main()
