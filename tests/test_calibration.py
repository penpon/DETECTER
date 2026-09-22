from __future__ import annotations

import hashlib
import io
import json
import math
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from detecter.calibration import calibrate_records, config_id_for, main, validate_config

CONDITION = {
    "model": "example",
    "model_version": "v1",
    "weights_version": "w1",
    "preprocessing_version": "p1",
}


def samples(specification):
    ledger, measurements = [], []
    for image_id, group, label, score in specification:
        digest = hashlib.sha256(image_id.encode()).hexdigest()
        ledger.append(
            {
                "image_id": image_id,
                "sha256": digest,
                "source_group": group,
                "label": label,
                "split": "tuning",
            }
        )
        measurements.append(
            {
                "image_id": image_id,
                "sha256": digest,
                **CONDITION,
                "preprocessing": {"crop": 384},
                "status": "ok",
                "raw_score": score,
                "error": None,
            }
        )
    return ledger, measurements


class CalibrationTests(unittest.TestCase):
    def test_selects_reproducible_candidate_without_production_promotion(self):
        ledger, measurements = samples(
            [
                ("real", "r", "real", 0.1),
                ("real-derived", "r", "real", 0.2),
                ("generated", "g", "generated", 0.9),
                ("generated-derived", "g", "generated", 0.8),
            ]
        )
        config = calibrate_records(ledger, measurements)
        self.assertEqual(config["threshold"], 0.8)
        self.assertEqual(config["comparison"], ">=")
        self.assertEqual(config["status"], "candidate")
        self.assertEqual(config["usage"], "evaluation")
        self.assertEqual(
            config["selected_metrics"]["false_positive_rate"]["denominator"], 1
        )
        self.assertEqual(
            config["selected_metrics"]["generated_detection_rate"]["denominator"], 1
        )
        self.assertEqual(
            config,
            calibrate_records(list(reversed(ledger)), list(reversed(measurements))),
        )
        self.assertEqual(len(config["calibration_images"]), 4)
        self.assertTrue(config["config_id"])

    def test_equal_scores_cannot_be_split_and_unmet_never_passes_validation(self):
        ledger, measurements = samples(
            [("r", "r", "real", 0.5), ("g", "g", "generated", 0.5)]
        )
        config = calibrate_records(ledger, measurements)
        self.assertEqual(config["status"], "unmet")
        self.assertEqual(
            [item["threshold"] for item in config["candidates"]],
            [0.5, math.nextafter(0.5, math.inf)],
        )
        at_tie = config["candidates"][0]
        self.assertEqual(at_tie["metrics"]["false_positive_rate"]["rate"], 1.0)
        self.assertEqual(at_tie["metrics"]["generated_detection_rate"]["rate"], 1.0)
        self.assertFalse(any(item["meets_targets"] for item in config["candidates"]))
        with self.assertRaisesRegex(ValueError, "unmet"):
            validate_config(config)

    def test_false_positive_boundary_is_one_group_in_one_thousand(self):
        specification = [
            (f"r{index}", f"r{index}", "real", 0.9 if index == 0 else 0.1)
            for index in range(1000)
        ]
        specification.extend(
            (f"g{index}", f"g{index}", "generated", 0.9 if index < 9 else 0.0)
            for index in range(10)
        )
        ledger, measurements = samples(specification)
        config = calibrate_records(ledger, measurements)
        self.assertEqual(config["status"], "candidate")
        self.assertEqual(config["threshold"], 0.9)
        self.assertEqual(
            config["selected_metrics"]["false_positive_rate"]["rate"], 0.001
        )
        self.assertEqual(
            config["selected_metrics"]["generated_detection_rate"]["rate"], 0.9
        )
        rejected = calibrate_records(
            [row for row in ledger if row["image_id"] != "r999"],
            [row for row in measurements if row["image_id"] != "r999"],
        )
        self.assertEqual(rejected["status"], "unmet")

    def test_rejects_all_evaluation_rows_before_selection_and_extra_measurements(self):
        ledger, measurements = samples(
            [("r", "same", "real", 0.1), ("g", "g", "generated", 0.9)]
        )
        evaluation = {
            **ledger[0],
            "image_id": "evaluation-image",
            "split": "evaluation",
        }
        with self.assertRaisesRegex(ValueError, "non-tuning"):
            calibrate_records([*ledger, evaluation], measurements)
        with self.assertRaisesRegex(ValueError, "split=tuning"):
            calibrate_records(ledger, measurements, split="evaluation")
        with self.assertRaisesRegex(ValueError, "outside tuning"):
            calibrate_records(
                ledger,
                [*measurements, {**measurements[0], "image_id": "evaluation-image"}],
            )

    def test_rejects_missing_failed_mismatched_and_invalid_measurements(self):
        ledger, measurements = samples(
            [("r", "r", "real", 0.1), ("g", "g", "generated", 0.9)]
        )
        for change in (
            {"status": "error", "raw_score": None},
            {"raw_score": float("nan")},
            {"raw_score": True},
            {"sha256": "0" * 64},
            {"weights_version": "other"},
            {"preprocessing_version": "other"},
            {"preprocessing": None},
            {"split": "evaluation"},
            {"source_group": "outside-tuning"},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                calibrate_records(
                    ledger, [{**measurements[0], **change}, measurements[1]]
                )
        for rows, scores in (
            ([], []),
            (ledger, measurements[:1]),
            (ledger, measurements * 2),
            (ledger[:1], measurements[:1]),
        ):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                calibrate_records(rows, scores)

    def test_candidate_only_applies_to_matching_evaluation_measurements(self):
        ledger, measurements = samples(
            [("r", "r", "real", 0.1), ("g", "g", "generated", 0.9)]
        )
        config = calibrate_records(ledger, measurements)
        validate_config(config, measurements[0])
        with self.assertRaisesRegex(ValueError, "production"):
            validate_config(config, measurements[0], usage="production")
        with self.assertRaisesRegex(ValueError, "condition mismatch"):
            validate_config(config, {**measurements[0], "model_version": "other"})

    def test_config_validation_requires_identity_targets_and_provenance(self):
        ledger, measurements = samples(
            [("r", "r", "real", 0.1), ("g", "g", "generated", 0.9)]
        )
        config = calibrate_records(ledger, measurements)
        for change in (
            {"calibration_id": "unknown"},
            {"calibration_images": []},
            {
                "calibration_images": [
                    {"image_id": "r", "sha256": "bad", "source_group": "r"}
                ]
            },
            {"targets": {}},
            {"required_provenance": "c2pa"},
            {"required_provenance": ["c2pa", "c2pa"]},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                invalid = {**config, **change}
                invalid["config_id"] = config_id_for(invalid)
                validate_config(invalid)
        with self.assertRaisesRegex(ValueError, "config_id"):
            validate_config({**config, "threshold": 0.8})
        approved = {**config, "status": "validated", "usage": "production"}
        approved["config_id"] = config_id_for(approved)
        validate_config(approved, measurements[0], usage="production")

    def test_cli_saves_config_without_images_or_overwriting(self):
        ledger, measurements = samples(
            [("r", "r", "real", 0.1), ("g", "g", "generated", 0.9)]
        )
        for row in ledger:
            row.update(
                path=f"{row['image_id']}.png",
                source="synthetic",
                license="CC0",
                history=[],
            )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger_file, measurement_file, output = (
                root / "ledger.jsonl",
                root / "measurements.jsonl",
                root / "config.json",
            )
            ledger_file.write_text("\n".join(json.dumps(row) for row in ledger))
            measurement_file.write_text(
                "\n".join(json.dumps(row) for row in measurements)
            )
            arguments = [
                "--ledger",
                str(ledger_file),
                "--measurements",
                str(measurement_file),
                "--split",
                "tuning",
                "--output",
                str(output),
            ]
            self.assertEqual(main(arguments), 0)
            self.assertEqual(json.loads(output.read_text())["status"], "candidate")
            before = output.read_bytes()
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(arguments), 2)
            self.assertEqual(output.read_bytes(), before)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main([*arguments[:-1], "-"]), 0)


if __name__ == "__main__":
    unittest.main()
