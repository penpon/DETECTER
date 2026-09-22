from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from detecter.calibration import TARGETS, config_id_for
from detecter.pipeline import main, one_sided_upper_bound, run_pipeline

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
        {"image_id": row["image_id"], "model": model}
        for row in ledger
        for model in ("ufd", "community-forensics-384")
    ]
    conditions = [
        {"condition": {"operation": "jpeg", "jpeg_quality": quality}}
        for quality in (95, 85, 75)
    ] + [
        {"condition": {"operation": "resize", "long_side": size}}
        for size in (1024, 512)
    ]
    return comparisons, conditions


class PipelineTests(unittest.TestCase):
    def test_zero_false_positives_at_3000_has_required_upper_bound(self):
        upper = one_sided_upper_bound(0, 3000)
        self.assertAlmostEqual(upper, 0.0009983, places=6)
        self.assertGreater(one_sided_upper_bound(1, 4500), 0.001)

    def test_synthetic_final_evaluation_is_achieved_only_with_enough_evidence(self):
        ledger = rows(real=3000, generated=10)
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
        self.assertEqual(report["stages"]["comparison"]["status"], "ok")

    def test_missing_measurements_is_evidence_insufficient(self):
        report = run_pipeline(rows(real=2, generated=1), config())
        self.assertEqual(report["status"], "insufficient_evidence")
        self.assertIn("measurements_missing", report["unverified"])

    def test_bad_final_evaluation_is_not_met(self):
        ledger = rows(real=3000, generated=10)
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
