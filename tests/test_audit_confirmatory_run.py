import json
import tempfile
import unittest
from pathlib import Path

from repair_agent.data_builder import generate_paired_dataset, load_tasks
from scripts.audit_confirmatory_run import CONFIRM_ARMS, audit


class AuditConfirmatoryRunTests(unittest.TestCase):
    def test_reports_group_when_every_first_response_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            run = root / "run"
            generate_paired_dataset(data, pairs=1, seed=7, split="test", entities=6)
            tasks = load_tasks(data / "public.jsonl")
            run.mkdir()
            (run / "public_tasks.jsonl").write_bytes((data / "public.jsonl").read_bytes())
            (run / "manifest.json").write_text(
                json.dumps({"arms": list(CONFIRM_ARMS), "repeats": 1}), encoding="utf-8"
            )

            rows = []
            for task_index, task in enumerate(tasks):
                for arm in CONFIRM_ARMS:
                    trajectory = (
                        [{"round": 1, "status": "FAIL", "response": "same", "keep_ids": []}]
                        if task_index == 0
                        else [{"round": 1, "status": "REQUEST_UNCERTAIN", "keep_ids": None}]
                    )
                    rows.append(
                        {
                            "task_id": task["task_id"],
                            "arm": arm,
                            "repeat": 0,
                            "trajectory": trajectory,
                        }
                    )
            (run / "results.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
            )

            result = audit(run, min_policy_differences=0)

            self.assertFalse(result["checks"]["paired_first_responses"])
            self.assertEqual(result["complete_first_response_groups"], 1)
            self.assertEqual(
                result["missing_first_response_groups"],
                [{"task_id": tasks[1]["task_id"], "repeat": 0, "present": []}],
            )


if __name__ == "__main__":
    unittest.main()
