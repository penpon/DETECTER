from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from detecter.calibration import TARGETS, config_id_for
from detecter.cli import apply_decision, main


def decision_config(
    *, threshold: float = 0.7, required_provenance: list[str] | None = None
) -> dict:
    config = {
        "schema_version": 1,
        "calibration_id": "a" * 64,
        "calibration_images": [
            {"image_id": "tuning-1", "sha256": "b" * 64, "source_group": "tuning-1"}
        ],
        "model": "ufd",
        "model_version": "model-1",
        "weights_version": "weights-1",
        "preprocessing_version": "pre-1",
        "split": "tuning",
        "threshold": threshold,
        "comparison": ">=",
        "targets": dict(TARGETS),
        "status": "candidate",
        "usage": "evaluation",
        "required_provenance": required_provenance or [],
        "candidates": [],
        "selected_metrics": {},
        "source_group_counts": {"real": 1, "generated": 1},
        "excluded_labels": ["edited", "unknown"],
        "group_policy": "any_positive_real; all_positive_generated",
        "selection_policy": "test",
    }
    return {**config, "config_id": config_id_for(config)}


def measurement(*, score: float = 0.8, **overrides: object) -> dict:
    return {
        "status": "ok",
        "raw_score": score,
        "model": "ufd",
        "model_version": "model-1",
        "weights_version": "weights-1",
        "preprocessing_version": "pre-1",
        **overrides,
    }


class DecisionCliTests(unittest.TestCase):
    def test_applies_matching_config_and_separates_partial_provenance(self):
        record = {
            "media": {"sha256": "c" * 64},
            "c2pa": {"generation_scope": "partial", "confirmed": True},
            "universal_fake_detect": measurement(),
        }
        decision = apply_decision(record, decision_config())
        self.assertEqual(decision["state"], "ai_likely")
        self.assertEqual(decision["config_id"], decision_config()["config_id"])
        self.assertEqual(decision["generation_scope"], "partial")
        self.assertNotIn("ai_evidence_confirmed", decision["state"])

    def test_mismatch_missing_config_and_required_provenance_hold(self):
        record = {
            "c2pa": {"confirmed": False},
            "universal_fake_detect": measurement(weights_version="wrong"),
        }
        decision = apply_decision(
            record, decision_config(required_provenance=["confirmed"])
        )
        self.assertEqual(decision["state"], "inconclusive")
        self.assertIn("measurement_condition_mismatch", decision["reasons"])
        self.assertIn("provenance_confirmed_missing", decision["reasons"])
        missing = apply_decision(
            record, None, config_error="decision config is missing"
        )
        self.assertEqual(missing["state"], "inconclusive")
        self.assertIn("config_missing", missing["reasons"])
        hashed = {
            "media": {"sha256": "c" * 64},
            "universal_fake_detect": measurement(sha256="d" * 64),
        }
        self.assertIn(
            "measurement_hash_mismatch",
            apply_decision(hashed, decision_config())["reasons"],
        )
        for field, value in (
            ("signature_state", "invalid"),
            ("trust_state", "untrusted"),
            ("status", "error"),
        ):
            with self.subTest(field=field):
                record = {
                    "media": {"sha256": "c" * 64},
                    "c2pa": {field: value},
                    "universal_fake_detect": measurement(),
                }
                decision = apply_decision(
                    record, decision_config(required_provenance=[field])
                )
                self.assertEqual(decision["state"], "inconclusive")

    def test_common_cli_dispatches_evaluate_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("ledger", "measurements", "decisions"):
                (root / name).write_text("", encoding="utf-8")
            output = root / "report.json"
            self.assertEqual(
                main(
                    [
                        "evaluate",
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
            self.assertEqual(json.loads(output.read_text())["target_count"], 0)

    def test_cli_uses_config_threshold_and_keeps_provenance_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "image.png"
            config = root / "decision.json"
            Image.new("RGB", (16, 16), "white").save(image)
            config.write_text(json.dumps(decision_config()))

            class Detector:
                def score(self, path: Path) -> float:
                    return 0.8

                def metadata(self) -> dict[str, str]:
                    return measurement()

            with (
                patch("detecter.cli.UfdDetector", return_value=Detector()),
                redirect_stdout(io.StringIO()) as output,
            ):
                code = main(
                    [
                        "analyze",
                        str(image),
                        "--decision-config",
                        str(config),
                        "--skip-c2pa",
                        "--output",
                        "-",
                    ]
                )
            self.assertEqual(code, 0)
            record = json.loads(output.getvalue())
            self.assertEqual(record["decision"]["state"], "ai_likely")
            self.assertEqual(
                record["decision"]["config_id"], decision_config()["config_id"]
            )
            self.assertEqual(record["c2pa"]["status"], "skipped")

    def test_invalid_config_fails_without_silent_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "image.png"
            config = root / "decision.json"
            Image.new("RGB", (8, 8), "white").save(image)
            config.write_text(json.dumps({"status": "unmet"}))
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "analyze",
                        str(image),
                        "--decision-config",
                        str(config),
                        "--skip-ufd",
                        "--output",
                        "-",
                    ]
                )
            self.assertEqual(code, 2)
            self.assertEqual(output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
