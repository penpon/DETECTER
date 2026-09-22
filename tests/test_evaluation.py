import unittest

from detecter.evaluation import evaluate_records

CONDITION = {
    "model": "ufd",
    "model_version": "v1",
    "weights_version": "w1",
    "preprocessing_version": "p1",
}


class EvaluationTests(unittest.TestCase):
    def test_counts_failures_missing_and_groups_without_inflating_samples(self):
        ledger = [
            {
                "image_id": name,
                "sha256": name * 64,
                "source_group": group,
                "label": label,
                "split": "evaluation",
                "history": [],
            }
            for name, group, label in [
                ("a", "real", "real"),
                ("b", "real", "real"),
                ("c", "gen", "generated"),
                ("d", "fail", "generated"),
                ("e", "missing", "edited"),
            ]
        ]
        measurements = [
            dict(
                image_id=r["image_id"],
                sha256=r["sha256"],
                status="error" if r["image_id"] == "d" else "ok",
                raw_score=None if r["image_id"] == "d" else 0.7,
                **CONDITION,
            )
            for r in ledger[:-1]
        ]
        decisions = [
            dict(
                image_id=r["image_id"],
                sha256=r["sha256"],
                state="no_ai_signal_detected" if r["image_id"] == "a" else "ai_likely",
                config_id="fixed",
                reasons=[],
                **CONDITION,
            )
            for r in ledger[:3]
        ]
        report = evaluate_records(ledger, measurements, decisions)
        self.assertEqual(report["metrics"]["false_positive_rate"]["numerator"], 1)
        self.assertEqual(report["metrics"]["false_positive_rate"]["denominator"], 2)
        self.assertEqual(report["metrics"]["generated_detection_rate"]["rate"], 0.5)
        self.assertEqual(
            report["metrics"]["edited_detection_rate"]["status"], "not_measured"
        )
        self.assertEqual(report["metrics"]["failure_rate"]["numerator"], 1)
        self.assertEqual(report["metrics"]["hold_rate"]["numerator"], 2)
        self.assertEqual(report["reversals"]["source_groups"], ["real"])
        grouped = evaluate_records(ledger, measurements, decisions, unit="source_group")
        self.assertEqual(grouped["metrics"]["false_positive_rate"]["denominator"], 1)
        self.assertEqual(grouped["metrics"]["false_positive_rate"]["rate"], 1.0)
        self.assertEqual(grouped["target_count"], 4)

    def test_empty_and_condition_mismatch_are_not_success(self):
        report = evaluate_records([], [], [])
        self.assertIsNone(report["metrics"]["false_positive_rate"]["rate"])
        row = {
            "image_id": "a",
            "sha256": "a" * 64,
            "source_group": "a",
            "label": "generated",
            "split": "evaluation",
            "history": [],
        }
        measurement = dict(
            image_id="a", sha256=row["sha256"], status="ok", raw_score=0.9, **CONDITION
        )
        decision = dict(
            image_id="a",
            sha256=row["sha256"],
            state="ai_likely",
            config_id="fixed",
            **{**CONDITION, "weights_version": "wrong"},
        )
        report = evaluate_records([row], [measurement], [decision])
        self.assertEqual(report["metrics"]["generated_detection_rate"]["numerator"], 0)
        self.assertIn("condition_mismatch", report["targets"][0]["reasons"])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            evaluate_records([row], [measurement, measurement], [decision])


if __name__ == "__main__":
    unittest.main()
