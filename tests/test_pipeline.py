from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from detecter.calibration import TARGETS, config_id_for
from detecter.pipeline import (
    main,
    one_sided_lower_bound,
    one_sided_upper_bound,
    run_pipeline,
)

CONDITION = {
    "model": "ufd",
    "model_version": "model-1",
    "weights_version": "weights-1",
    "preprocessing_version": "pre-1",
}


def config() -> dict:
    value = {
        "schema_version": 1,
        "calibration_id": "a" * 64,
        "calibration_images": [
            {"image_id": "tuning", "sha256": "b" * 64, "source_group": "tuning"}
        ],
        **CONDITION,
        "split": "tuning",
        "threshold": 0.5,
        "comparison": ">=",
        "targets": dict(TARGETS),
        "status": "candidate",
        "usage": "evaluation",
        "required_provenance": [],
        "candidates": [],
        "selected_metrics": {},
        "source_group_counts": {"real": 3000, "generated": 10},
        "excluded_labels": ["edited", "unknown"],
        "group_policy": "any_positive_real; all_positive_generated",
        "selection_policy": "test",
    }
    return {**value, "config_id": config_id_for(value)}


def rows(real: int = 0, generated: int = 0) -> list[dict]:
    result = []
    for label, count in (("real", real), ("generated", generated)):
        for index in range(count):
            name = f"{label}-{index}"
            result.append(
                {
                    "image_id": name,
                    "sha256": f"{index + (0 if label == 'real' else 10000):064x}",
                    "source_group": name,
                    "source": "verified-corpus",
                    "license": "test",
                    "label": label,
                    "split": "evaluation",
                    "history": [],
                }
            )
    return result


def records(ledger: list[dict], score: float = 0.8) -> tuple[list[dict], list[dict]]:
    measurements, decisions = [], []
    for row in ledger:
        measurements.append(
            {
                **CONDITION,
                "image_id": row["image_id"],
                "sha256": row["sha256"],
                "status": "ok",
                "raw_score": score,
            }
        )
        decisions.append(
            {
                **CONDITION,
                "image_id": row["image_id"],
                "sha256": row["sha256"],
                "config_id": config()["config_id"],
                "state": "ai_likely",
                "reasons": [],
            }
        )
    return measurements, decisions


def processing(ledger: list[dict]) -> tuple[list[dict], list[dict]]:
    comparisons = [
        {
            "image_id": row["image_id"],
            "sha256": row["sha256"],
            "model": model,
            "status": "ok",
        }
        for row in ledger
        for model in ("ufd", "community-forensics-384")
    ]
    conditions = []
    for row in ledger:
        conditions.extend(
            {
                "source_image_id": row["image_id"],
                "source_sha256": row["sha256"],
                "status": "created",
                "condition": {"operation": "jpeg", "jpeg_quality": quality},
            }
            for quality in (95, 85, 75)
        )
        conditions.extend(
            {
                "source_image_id": row["image_id"],
                "source_sha256": row["sha256"],
                "status": "created",
                "condition": {"operation": "resize", "long_side": size},
            }
            for size in (1024, 512)
        )
    return comparisons, conditions


def add_stratification(ledger: list[dict]) -> None:
    for row in ledger:
        if row["label"] == "real":
            row["camera"] = "camera-a"
        elif row["label"] == "generated":
            row["generator"] = "gen-a"
    ledger.append(
        {
            "image_id": "edited-0",
            "sha256": "c" * 64,
            "source_group": "edited-0",
            "source": "verified-corpus",
            "license": "test",
            "label": "edited",
            "split": "evaluation",
            "history": [],
            "generator": "gen-a",
            "camera": "camera-a",
        }
    )


class PipelineTests(unittest.TestCase):
    def test_zero_false_positives_at_3000_has_required_upper_bound(self):
        upper = one_sided_upper_bound(0, 3000)
        self.assertAlmostEqual(upper, 0.0009983, places=6)
        self.assertGreater(one_sided_upper_bound(1, 4500), 0.001)

    def test_synthetic_final_evaluation_is_achieved_only_with_enough_evidence(self):
        # 30/30全検出で片側95%下限が約0.905となり90%目標を満たす。
        ledger = rows(real=3000, generated=30)
        add_stratification(ledger)
        measurements, decisions = records(ledger)
        for row in ledger[:3000]:
            decisions[ledger.index(row)]["state"] = "no_ai_signal_detected"
        comparisons, conditions = processing(ledger)
        report = run_pipeline(
            ledger,
            config(),
            measurements=measurements,
            decisions=decisions,
            comparisons=comparisons,
            derived_conditions=conditions,
        )
        self.assertEqual(report["status"], "achieved")
        self.assertTrue(report["criteria"]["false_positive_upper_bound"]["passes"])
        self.assertTrue(report["criteria"]["generated_detection_rate"]["passes"])
        self.assertGreaterEqual(
            report["criteria"]["generated_detection_rate"]["lower"], 0.9
        )
        self.assertEqual(
            report["criteria"]["generated_detection_rate"]["method"],
            "clopper_pearson_one_sided",
        )
        self.assertEqual(report["stages"]["comparison"]["status"], "ok")

    def test_point_estimate_above_target_but_lower_below_is_not_met(self):
        # 点推定値90%でも信頼下限が90%未満なら達成にしない。
        ledger = rows(real=3000, generated=10)
        add_stratification(ledger)
        measurements, decisions = records(ledger)
        for row in ledger[:3000]:
            decisions[ledger.index(row)]["state"] = "no_ai_signal_detected"
        for row in ledger[3000 + 9 :]:
            decisions[ledger.index(row)]["state"] = "no_ai_signal_detected"
        comparisons, conditions = processing(ledger)
        report = run_pipeline(
            ledger,
            config(),
            measurements=measurements,
            decisions=decisions,
            comparisons=comparisons,
            derived_conditions=conditions,
        )
        criterion = report["criteria"]["generated_detection_rate"]
        self.assertEqual(criterion["numerator"], 9)
        self.assertEqual(criterion["denominator"], 10)
        self.assertEqual(criterion["rate"], 0.9)
        self.assertLess(criterion["lower"], 0.9)
        self.assertFalse(criterion["passes"])
        self.assertEqual(report["status"], "not_met")

    def test_unmet_required_generator_group_is_insufficient_evidence(self):
        ledger = rows(real=3000, generated=30)
        for row in ledger[:3000]:
            row["camera"] = "camera-a"
        for index, row in enumerate(ledger[3000:]):
            row["generator"] = "gen-a" if index < 29 else "gen-b"
        ledger.append(
            {
                "image_id": "edited-0",
                "sha256": "c" * 64,
                "source_group": "edited-0",
                "source": "verified-corpus",
                "license": "test",
                "label": "edited",
                "split": "evaluation",
                "history": [],
                "generator": "gen-a",
                "camera": "camera-a",
            }
        )
        measurements, decisions = records(ledger)
        for row in ledger[:3000]:
            decisions[ledger.index(row)]["state"] = "no_ai_signal_detected"
        comparisons, conditions = processing(ledger)
        report = run_pipeline(
            ledger,
            config(),
            measurements=measurements,
            decisions=decisions,
            comparisons=comparisons,
            derived_conditions=conditions,
            required_generators={"gen-a": 29, "gen-b": 2},
        )
        self.assertEqual(report["status"], "insufficient_evidence")
        self.assertIn("generator_group_insufficient:gen-b", report["unverified"])
        self.assertFalse(report["generator_coverage"]["met"])
        met = run_pipeline(
            ledger,
            config(),
            measurements=measurements,
            decisions=decisions,
            comparisons=comparisons,
            derived_conditions=conditions,
            required_generators={"gen-a": 29, "gen-b": 1},
        )
        self.assertEqual(met["status"], "achieved")
        self.assertTrue(met["generator_coverage"]["met"])

    def test_missing_stratification_never_reports_achieved(self):
        ledger = rows(real=3000, generated=30)
        for index, row in enumerate(ledger[3000:]):
            row["generator"] = "gen-a"
        measurements, decisions = records(ledger)
        for row in ledger[:3000]:
            decisions[ledger.index(row)]["state"] = "no_ai_signal_detected"
        comparisons, conditions = processing(ledger)
        report = run_pipeline(
            ledger,
            config(),
            measurements=measurements,
            decisions=decisions,
            comparisons=comparisons,
            derived_conditions=conditions,
            required_generators={"gen-a": 30},
        )
        self.assertEqual(report["status"], "insufficient_evidence")
        self.assertIn("camera_breakdown_not_provided", report["unverified"])
        self.assertIn("partial_edit_scope_not_evaluated", report["unverified"])

    def test_generator_coverage_excludes_edits_and_survives_missing_measurements(self):
        ledger = rows(real=1, generated=1)
        ledger[1]["generator"] = "gen-a"
        edited = {
            **ledger[1],
            "image_id": "edited-1",
            "sha256": "c" * 64,
            "source_group": "edited-1",
            "label": "edited",
        }
        ledger.append(edited)
        report = run_pipeline(
            ledger,
            config(),
            required_generators={"gen-a": 2},
        )
        self.assertEqual(report["status"], "insufficient_evidence")
        self.assertEqual(report["generator_coverage"]["actual"]["gen-a"], 1)
        self.assertFalse(report["generator_coverage"]["met"])
        self.assertIn("generator_group_insufficient:gen-a", report["unverified"])

    def test_lower_bound_helpers(self):
        self.assertIsNone(one_sided_lower_bound(0, 0))
        self.assertEqual(one_sided_lower_bound(0, 5), 0.0)
        self.assertAlmostEqual(one_sided_lower_bound(30, 30), 0.9049661, places=6)
        self.assertGreater(one_sided_lower_bound(29, 29), 0.9)
        self.assertLess(one_sided_lower_bound(10, 10), 0.9)
        with self.assertRaises(ValueError):
            one_sided_lower_bound(6, 5)
        with self.assertRaises(ValueError):
            one_sided_lower_bound(-1, 5)

    def test_missing_measurements_is_evidence_insufficient(self):
        report = run_pipeline(rows(real=2, generated=1), config())
        self.assertEqual(report["status"], "insufficient_evidence")
        self.assertIn("measurements_missing", report["unverified"])

    def test_invalid_evaluation_keeps_confidence_fields_as_insufficient(self):
        ledger = rows(real=2, generated=1)
        ledger[0]["label"] = "invalid"
        measurements, decisions = records(ledger)
        comparisons, conditions = processing(ledger)
        report = run_pipeline(
            ledger,
            config(),
            measurements=measurements,
            decisions=decisions,
            comparisons=comparisons,
            derived_conditions=conditions,
        )
        generated = report["criteria"]["generated_detection_rate"]
        self.assertEqual(report["status"], "insufficient_evidence")
        self.assertEqual(generated["status"], "insufficient_data")
        self.assertIsNone(generated["numerator"])
        self.assertIsNone(generated["denominator"])
        self.assertIsNone(generated["lower"])
        self.assertEqual(generated["confidence"], 0.95)
        self.assertEqual(generated["method"], "clopper_pearson_one_sided")

    def test_bad_final_evaluation_is_not_met(self):
        ledger = rows(real=3000, generated=10)
        add_stratification(ledger)
        measurements, decisions = records(ledger)
        for row in ledger[:1]:
            decisions[ledger.index(row)]["state"] = "ai_likely"
        comparisons, conditions = processing(ledger)
        report = run_pipeline(
            ledger,
            config(),
            measurements=measurements,
            decisions=decisions,
            comparisons=comparisons,
            derived_conditions=conditions,
        )
        self.assertEqual(report["status"], "not_met")
        self.assertFalse(report["criteria"]["false_positive_upper_bound"]["passes"])

    def test_unresolved_real_group_cannot_be_dropped_from_the_denominator(self):
        ledger = rows(real=3000, generated=10)
        measurements, decisions = records(ledger)
        measurements.pop(0)
        decisions.pop(0)
        comparisons, conditions = processing(ledger)
        report = run_pipeline(
            ledger,
            config(),
            measurements=measurements,
            decisions=decisions,
            comparisons=comparisons,
            derived_conditions=conditions,
        )
        self.assertEqual(report["status"], "insufficient_evidence")
        self.assertIn("real_measurement_missing_or_unresolved", report["unverified"])

    def test_saved_decision_from_another_config_cannot_be_adopted(self):
        ledger = rows(real=3000, generated=10)
        measurements, decisions = records(ledger)
        decisions[0]["config_id"] = "c" * 64
        comparisons, conditions = processing(ledger)
        report = run_pipeline(
            ledger,
            config(),
            measurements=measurements,
            decisions=decisions,
            comparisons=comparisons,
            derived_conditions=conditions,
        )
        self.assertEqual(report["status"], "insufficient_evidence")
        self.assertIn("decision_config_id_mismatch", report["unverified"])

    def test_failed_or_mismatched_comparison_is_not_complete(self):
        ledger = rows(real=3000, generated=10)
        measurements, decisions = records(ledger)
        comparisons, conditions = processing(ledger)
        comparisons[0]["status"] = "error"
        comparisons[1]["sha256"] = "f" * 64
        report = run_pipeline(
            ledger,
            config(),
            measurements=measurements,
            decisions=decisions,
            comparisons=comparisons,
            derived_conditions=conditions,
        )
        self.assertEqual(report["status"], "insufficient_evidence")
        self.assertEqual(report["stages"]["comparison"]["status"], "insufficient")
        generated = report["criteria"]["generated_detection_rate"]
        self.assertEqual((generated["numerator"], generated["denominator"]), (10, 10))
        self.assertEqual(generated["confidence"], 0.95)
        self.assertEqual(generated["method"], "clopper_pearson_one_sided")

    def test_mixed_synthetic_and_verified_rows_cannot_prove_performance(self):
        ledger = rows(real=3000, generated=10)
        ledger[0]["source"] = "synthetic-test"
        measurements, decisions = records(ledger)
        comparisons, conditions = processing(ledger)
        report = run_pipeline(
            ledger,
            config(),
            measurements=measurements,
            decisions=decisions,
            comparisons=comparisons,
            derived_conditions=conditions,
        )
        self.assertEqual(report["status"], "insufficient_evidence")
        self.assertIn("synthetic_data_not_performance_evidence", report["unverified"])

    def test_cli_writes_evidence_report_without_external_models(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "ledger.jsonl"
            config_path = root / "config.json"
            output = root / "report.json"
            ledger.write_text("\n")
            config_path.write_text(json.dumps(config()))
            self.assertEqual(
                main(
                    [
                        "--ledger",
                        str(ledger),
                        "--decision-config",
                        str(config_path),
                        "--output",
                        str(output),
                    ]
                ),
                0,
            )
            report = json.loads(output.read_text())
            self.assertEqual(report["status"], "insufficient_evidence")


if __name__ == "__main__":
    unittest.main()
