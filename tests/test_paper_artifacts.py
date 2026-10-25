import unittest

from scripts.build_paper_artifacts import (
    metric_value,
    paired_arm_effect,
    paired_track_effect,
    holm_adjust,
    validate_matrix,
)


def row(task, base, arm, repeat, track, status="PASS", repair=True, f1=0.8):
    return {
        "task_id": task,
        "base_instance_id": base,
        "arm": arm,
        "repeat": repeat,
        "track": track,
        "status": status,
        "is_repair": repair,
        "f1": f1,
        "mode": "LIVE",
    }


class PaperArtifactTests(unittest.TestCase):
    def test_incomplete_matrix_is_rejected(self):
        manifest = {"arms": ["B1", "B2"], "repeats": 2, "task_hashes": {"a": "x"}}
        rows = [row("a", "base", "B1", 0, "C0")]
        with self.assertRaisesRegex(ValueError, "incomplete"):
            validate_matrix(rows, manifest)

    def test_failed_result_has_zero_valid_f1(self):
        failed = row("a", "base", "B1", 0, "C0", status="ROUND_LIMIT", repair=False, f1=0.9)
        self.assertEqual(metric_value(failed, "valid_f1"), 0.0)

    def test_arm_effect_clusters_tracks_and_repeats_by_base(self):
        rows = []
        for track in ("C0", "C1"):
            task = "base_" + track
            for repeat in (0, 1):
                rows.append(row(task, "base", "B2", repeat, track, repair=True))
                rows.append(row(task, "base", "B1", repeat, track, repair=False))
        effect = paired_arm_effect(rows, "B2", "B1", "repair_rate", draws=100, seed=3)
        self.assertEqual(effect["n_base_instances"], 1)
        self.assertEqual(effect["absolute_difference"], 1.0)
        self.assertEqual(effect["ci95_low"], 1.0)
        self.assertEqual(effect["ci95_high"], 1.0)

    def test_track_effect_requires_same_base(self):
        rows = [
            row("a_C0", "a", "B2", 0, "C0", repair=False),
            row("b_C1", "b", "B2", 0, "C1", repair=True),
        ]
        with self.assertRaisesRegex(ValueError, "no paired"):
            paired_track_effect(rows, "B2", "repair_rate", draws=100, seed=4)

    def test_holm_fields_are_fixed_and_monotone(self):
        adjusted = holm_adjust([0.01, 0.04, 0.03])
        self.assertEqual([set(item) for item in adjusted], [
            {"p_value", "p_holm", "reject_0_05"},
            {"p_value", "p_holm", "reject_0_05"},
            {"p_value", "p_holm", "reject_0_05"},
        ])
        ordered = sorted(adjusted, key=lambda item: item["p_value"])
        self.assertEqual([item["p_holm"] for item in ordered], sorted(item["p_holm"] for item in ordered))


if __name__ == "__main__":
    unittest.main()
