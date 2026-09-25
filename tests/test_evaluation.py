import json
import tempfile
import unittest
from pathlib import Path

from detecter.evaluation import evaluate_records, main

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
        stale = evaluate_records([row], [{**measurement, "sha256": "b" * 64}], [])
        self.assertEqual(
            stale["metrics"]["generated_detection_rate"]["status"], "not_measured"
        )
        self.assertIsNone(stale["metrics"]["failure_rate"]["rate"])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            evaluate_records([row], [measurement, measurement], [decision])
        with self.assertRaisesRegex(ValueError, "conflicting"):
            evaluate_records(
                [row, {**row, "image_id": "b", "split": "tuning"}],
                [],
                [],
                split="evaluation",
            )

    def test_tpr_at_fpr_aggregates_group_scores_and_image_kinds(self):
        ledger, measurements = [], []
        for index in range(200):
            image_id = f"real-{index:03d}"
            ledger.append(
                {
                    "image_id": image_id,
                    "sha256": f"{index:064x}",
                    "source_group": f"rg{index:03d}",
                    "label": "real",
                    "split": "evaluation",
                    "history": [],
                    "image_kind": "photo" if index < 100 else "unknown",
                }
            )
            measurements.append(
                dict(
                    image_id=image_id,
                    sha256=f"{index:064x}",
                    status="ok",
                    raw_score=(index + 1) * 0.01,
                    **CONDITION,
                )
            )
        # A two-image real group aggregates member scores with max().
        for suffix, score in (("a", 0.10), ("b", 1.995)):
            image_id = f"real-pair-{suffix}"
            ledger.append(
                {
                    "image_id": image_id,
                    "sha256": image_id * 8,
                    "source_group": "rg-pair",
                    "label": "real",
                    "split": "evaluation",
                    "history": [],
                    "image_kind": "photo",
                }
            )
            measurements.append(
                dict(
                    image_id=image_id,
                    sha256=image_id * 8,
                    status="ok",
                    raw_score=score,
                    **CONDITION,
                )
            )
        # Generated groups aggregate with min(): every member must reach the
        # threshold, and an unmeasured member keeps the group undetected but
        # inside the denominator.
        generated = [[(f"gen-{index}", 2.5)] for index in range(8)] + [
            [("gen-pair-hi", 2.5), ("gen-pair-lo", 2.0)],
            [("gen-miss-hi", 2.5), ("gen-miss-lo", 0.1)],
            [("gen-gap-a", 2.5), ("gen-gap-b", None)],
        ]
        for group_index, images in enumerate(generated):
            for image_index, (image_id, score) in enumerate(images):
                sha = f"g{group_index}{image_index}" + "0" * 60
                ledger.append(
                    {
                        "image_id": image_id,
                        "sha256": sha,
                        "source_group": f"gg{group_index:03d}",
                        "label": "generated",
                        "split": "evaluation",
                        "history": [],
                        "image_kind": "photo",
                    }
                )
                if score is not None:
                    measurements.append(
                        dict(
                            image_id=image_id,
                            sha256=sha,
                            status="ok",
                            raw_score=score,
                            **CONDITION,
                        )
                    )
        report = evaluate_records(ledger, measurements, [])
        tpr = report["tpr_at_fpr"]
        self.assertEqual(tpr["unit"], "source_group")
        overall = tpr["overall"]
        self.assertEqual(overall["status"], "measured")
        self.assertEqual(overall["real_groups"], 201)
        # 201 real groups allow floor(201*0.01)=2 and floor(201*0.001)=0 FPs.
        low = overall["targets"]["0.01"]
        self.assertEqual(low["allowed_false_positives"], 2)
        # The threshold sits just above the 3rd largest real score (1.99) so
        # that exactly 2 real groups (2.00 and the pair's max 1.995) cross it.
        self.assertAlmostEqual(low["threshold"], 1.99)
        self.assertGreater(low["threshold"], 1.99)
        self.assertEqual(low["false_positives"], 2)
        self.assertEqual(low["generated"]["detected"], 9)
        self.assertEqual(low["generated"]["groups"], 11)
        self.assertAlmostEqual(low["generated"]["tpr"], 9 / 11)
        strict = overall["targets"]["0.001"]
        self.assertEqual(strict["allowed_false_positives"], 0)
        self.assertEqual(strict["false_positives"], 0)
        self.assertGreater(strict["threshold"], 2.0)
        self.assertEqual(strict["generated"]["detected"], 8)
        photo = tpr["by_image_kind"]["photo"]
        self.assertEqual(photo["real_groups"], 101)
        photo_low = photo["targets"]["0.01"]
        self.assertEqual(photo_low["allowed_false_positives"], 1)
        # 101 photo real groups keep the 2nd largest score (1.00) out.
        self.assertAlmostEqual(photo_low["threshold"], 1.0)
        self.assertEqual(photo_low["false_positives"], 1)
        self.assertEqual(photo_low["generated"]["detected"], 9)
        unknown = tpr["by_image_kind"]["unknown"]
        self.assertEqual(unknown["real_groups"], 100)
        self.assertEqual(unknown["targets"]["0.01"]["allowed_false_positives"], 1)
        self.assertIsNone(unknown["targets"]["0.01"]["generated"]["tpr"])
        self.assertEqual(
            sorted(report["breakdowns"]["image_kind"]), ["photo", "unknown"]
        )

    def test_cli_reads_saved_files_and_writes_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("ledger", "measurements", "decisions"):
                (root / name).write_text("", encoding="utf-8")
            output = root / "report.json"
            self.assertEqual(
                main(
                    [
                        "--ledger",
                        str(root / "ledger"),
                        "--measurements",
                        str(root / "measurements"),
                        "--decisions",
                        str(root / "decisions"),
                        "--output",
                        str(output),
                    ]
                ),
                0,
            )
            report = json.loads(output.read_text())
            self.assertEqual(report["target_count"], 0)
            self.assertEqual(
                report["metrics"]["failure_rate"]["status"], "insufficient_data"
            )


if __name__ == "__main__":
    unittest.main()
