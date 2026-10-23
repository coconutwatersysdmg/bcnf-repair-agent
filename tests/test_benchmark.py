import tempfile
import unittest
from pathlib import Path


class BenchmarkTests(unittest.TestCase):
    def test_generated_instances_are_repairs_for_all_backends(self):
        from scripts.benchmark_bcnf_backends import build_instance, check_all_backends

        for family in ("single", "dual", "composite"):
            schema, rows, retained = build_instance(40, family, 0.15, seed=7)
            verdicts = check_all_backends(schema, rows, retained, include_fullscan=True)
            self.assertEqual(
                {name: (value.is_repair, value.candidate_consistent)
                 for name, value in verdicts.items()},
                {
                    "bcnf_index": (True, True),
                    "fd_hash": (True, True),
                    "singleton_fullscan": (True, True),
                },
            )

    def test_small_matrix_writes_raw_and_summary_rows(self):
        from scripts.benchmark_bcnf_backends import run_matrix, write_report_and_figure

        with tempfile.TemporaryDirectory() as tmp:
            raw, summary = run_matrix(
                output_dir=Path(tmp),
                row_counts=[40],
                families=["single"],
                conflict_ratios=[0.10],
                seeds=[1],
                repetitions=2,
                fullscan_max_rows=100,
            )
            self.assertTrue(raw.is_file())
            self.assertTrue(summary.is_file())
            text = summary.read_text(encoding="utf-8")
            self.assertIn("median_decision_ns", text)
            self.assertIn("p95_decision_ns", text)
            self.assertIn("bcnf_index", text)
            self.assertIn("fd_hash", text)
            self.assertIn("singleton_fullscan", text)
            report = Path(tmp) / "report.md"
            figure = Path(tmp) / "scaling.svg"
            write_report_and_figure(summary, report, figure)
            self.assertIn("100%", report.read_text(encoding="utf-8"))
            self.assertIn("<svg", figure.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
