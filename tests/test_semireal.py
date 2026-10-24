import json
import tempfile
import unittest
from pathlib import Path

from repair_agent.checker import decision
from repair_agent.domain import canonical


class SemirealDatasetTests(unittest.TestCase):
    def source_rows(self):
        return [
            {"record_id": f"id{i}", "date": f"2026-01-{i + 1:02d}",
             "value": str(100 + i), "group": f"g{i % 3}"}
            for i in range(24)
        ]

    def test_pairs_share_real_rows_and_hidden_truth(self):
        from repair_agent.semireal import build_semireal_tasks

        source = self.source_rows()
        public, private, metadata = build_semireal_tasks(
            "fixture", source, key_fields=["record_id"], pairs=5,
            entities=8, seed=9, split="test",
        )
        self.assertEqual(len(public), 10)
        self.assertEqual(metadata["base_instances"], 5)
        truth = {row["task_id"]: row for row in private}
        source_values = {tuple(row.values()) for row in source}
        by_base = {}
        for task in public:
            by_base.setdefault(task["base_instance_id"], []).append(task)
            self.assertNotIn("true_ids", canonical(task))
            true_values = {
                tuple(record["values"])
                for record in task["records"]
                if record["id"] in truth[task["task_id"]]["true_ids"]
            }
            self.assertTrue(true_values <= source_values)
            self.assertTrue(decision(task, truth[task["task_id"]]["true_ids"])["consistent"])
        self.assertEqual(len(by_base), 5)
        for pair in by_base.values():
            self.assertEqual({task["track"] for task in pair}, {"C0", "C1"})
            c0, c1 = sorted(pair, key=lambda task: task["track"])
            for field in ("schema", "records", "initial_keep_ids", "category", "family"):
                self.assertEqual(c0[field], c1[field])
            self.assertEqual(truth[c0["task_id"]]["true_ids"], truth[c1["task_id"]]["true_ids"])
            self.assertEqual(c0["source_evidence"], {})
            self.assertEqual(set(c1["source_evidence"]), {r["id"] for r in c1["records"]})

    def test_conflict_categories_really_violate_the_source_key_fd(self):
        from repair_agent.semireal import build_semireal_tasks

        public, _, _ = build_semireal_tasks(
            "fixture", self.source_rows(), key_fields=["record_id"],
            pairs=5, entities=8, seed=9, split="test",
        )
        by_category = {task["category"]: task for task in public if task["track"] == "C0"}
        for category in ("residual", "mixed", "ambiguous"):
            task = by_category[category]
            all_ids = [record["id"] for record in task["records"]]
            self.assertFalse(decision(task, all_ids)["consistent"])
        over = by_category["over_deletion"]
        self.assertTrue(decision(over, over["initial_keep_ids"])["consistent"])
        self.assertFalse(decision(over, over["initial_keep_ids"])["is_repair"])

    def test_official_uci_archives_have_expected_unique_ids(self):
        from repair_agent.semireal import load_bike_source, load_wdbc_source

        root = Path(__file__).resolve().parents[1] / "sources" / "uci"
        bike = load_bike_source(root / "bike_sharing_275.zip")
        cancer = load_wdbc_source(root / "breast_cancer_diagnostic_17.zip")
        self.assertEqual(len(bike), 17379)
        self.assertEqual(len({row["instant"] for row in bike}), 17379)
        self.assertEqual(len(cancer), 569)
        self.assertEqual(len({row["ID"] for row in cancer}), 569)
        self.assertEqual(
            list(bike[0]),
            ["instant", "dteday", "season", "hr", "weathersit", "temp", "hum", "windspeed", "cnt"],
        )
        self.assertEqual(
            list(cancer[0]),
            ["ID", "Diagnosis", "radius1", "texture1", "perimeter1", "area1",
             "smoothness1", "compactness1", "concavity1", "concave_points1"],
        )

    def test_writer_freezes_provenance_and_refuses_overwrite(self):
        from repair_agent.semireal import build_semireal_tasks, write_semireal_dataset

        public, private, metadata = build_semireal_tasks(
            "fixture", self.source_rows(), key_fields=["record_id"],
            pairs=5, entities=8, seed=9, split="test",
        )
        source = {
            "url": "https://example.test/source.zip", "license": "CC BY 4.0",
            "doi": "10.test/example", "archive_sha256": "abc123",
            "archive_name": "source.zip", "downloaded_on": "2026-10-24",
        }
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "dataset"
            manifest = write_semireal_dataset(target, public, private, metadata, source)
            self.assertEqual(manifest["source"]["archive_sha256"], "abc123")
            self.assertEqual(manifest["source"]["license"], "CC BY 4.0")
            self.assertEqual(len((target / "public.jsonl").read_text(encoding="utf-8").splitlines()), 10)
            self.assertNotIn("true_ids", (target / "public.jsonl").read_text(encoding="utf-8"))
            self.assertIn("10.test/example", (target / "README.md").read_text(encoding="utf-8"))
            with self.assertRaises(FileExistsError):
                write_semireal_dataset(target, public, private, metadata, source)

    def test_build_entrypoint_creates_both_domains(self):
        from scripts.build_semireal_datasets import build_all

        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            outputs = build_all(
                root / "sources" / "uci", Path(tmp), pairs=5, entities=8,
                downloaded_on="2026-10-24",
            )
            self.assertEqual(set(outputs), {"bike", "wdbc"})
            for path in outputs.values():
                self.assertEqual(len((path / "public.jsonl").read_text(encoding="utf-8").splitlines()), 10)
                self.assertTrue((path / "README.md").is_file())

    def test_build_entrypoint_uses_explicit_tag_for_independent_dataset(self):
        from scripts.build_semireal_datasets import build_all

        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            outputs = build_all(
                root / "sources" / "uci", Path(tmp), pairs=5, entities=8,
                downloaded_on="2026-10-25", tag="rep90_20261025",
                seed_base=2026102500,
            )
            self.assertEqual(outputs["bike"].name, "semireal_bike_rep90_20261025")
            self.assertEqual(outputs["wdbc"].name, "semireal_wdbc_rep90_20261025")
            manifest = json.loads((outputs["bike"] / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["base_instances"], 5)
            self.assertEqual(manifest["seed"], 2026102501)


if __name__ == "__main__":
    unittest.main()
