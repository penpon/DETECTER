from __future__ import annotations

import math
import statistics
import unittest

from detecter.base_probability import (
    BIAS,
    CALIBRATION_SPLIT,
    MODEL_VERSION,
    calibrated_ai_probability,
)

# Fixed score table recorded on the tuning split (CF384 logit / CuRe softmax / UFD sigmoid).
REAL_SCORES = [
    (-6.0, 0.10, 0.90),
    (-7.0, 0.05, 0.85),
    (-5.5, 0.15, 0.95),
    (-8.0, 0.03, 0.80),
    (-5.0, 0.20, 0.95),
    (-6.5, 0.08, 0.88),
    (-7.5, 0.04, 0.92),
    (-9.0, 0.02, 0.75),
    (-6.0, 0.12, 0.90),
    (-5.8, 0.10, 0.93),
]
GENERATED_SCORES = [
    (-3.0, 0.80, 0.60),
    (-4.0, 0.85, 0.70),
    (-3.5, 0.75, 0.65),
    (-4.5, 0.90, 0.75),
    (-3.0, 0.90, 0.55),
    (-5.0, 0.95, 0.70),
    (-2.5, 0.70, 0.50),
    (-4.2, 0.88, 0.72),
    (-3.8, 0.82, 0.68),
    (-2.8, 0.78, 0.58),
]


def _auc(positive: list[float], negative: list[float]) -> float:
    wins = sum(
        1.0 if p > n else 0.5 if p == n else 0.0 for p in positive for n in negative
    )
    return wins / (len(positive) * len(negative))


class BaseProbabilityTests(unittest.TestCase):
    def test_matches_logistic_of_weighted_scores(self):
        cf, cure, ufd = -5.0, 0.8, 0.65
        result = calibrated_ai_probability(cf, cure, ufd)
        expected_logit = BIAS + 0.5185 * cf + 2.7269 * cure - 3.0123 * ufd
        self.assertAlmostEqual(result["logit"], expected_logit)
        self.assertAlmostEqual(
            result["probability"], 1.0 / (1.0 + math.exp(-expected_logit))
        )
        self.assertTrue(0.0 <= result["probability"] <= 1.0)
        self.assertFalse(result["partial"])
        self.assertEqual(result["missing_scores"], [])

    def test_default_weights_and_model_condition_are_recorded(self):
        result = calibrated_ai_probability(-5.0, 0.8, 0.65)
        self.assertEqual(
            result["weights"],
            {"cf_score": 0.5185, "cure_score": 2.7269, "ufd_score": -3.0123},
        )
        self.assertEqual(result["bias"], 3.5753)
        condition = result["model_condition"]
        for key in (
            "model",
            "model_version",
            "weights_version",
            "preprocessing_version",
        ):
            self.assertTrue(condition[key])
        self.assertEqual(condition["model_version"], MODEL_VERSION)
        self.assertEqual(condition["calibration_split"], CALIBRATION_SPLIT)

    def test_missing_scores_partial_calculation_marks_uncertainty(self):
        result = calibrated_ai_probability(-5.0, ufd_score=0.9)
        self.assertTrue(result["partial"])
        self.assertEqual(result["missing_scores"], ["cure_score"])
        expected = 1.0 / (1.0 + math.exp(-(BIAS + 0.5185 * -5.0 - 3.0123 * 0.9)))
        self.assertAlmostEqual(result["probability"], expected)
        with self.assertRaises(ValueError):
            calibrated_ai_probability()
        with self.assertRaises(ValueError):
            calibrated_ai_probability(float("nan"), 0.5, 0.5)

    def test_real_and_generated_groups_separate_on_recorded_scores(self):
        real = [calibrated_ai_probability(*row)["probability"] for row in REAL_SCORES]
        generated = [
            calibrated_ai_probability(*row)["probability"] for row in GENERATED_SCORES
        ]
        self.assertAlmostEqual(statistics.median(real), 0.10, delta=0.05)
        self.assertAlmostEqual(statistics.median(generated), 0.88, delta=0.05)
        self.assertGreaterEqual(_auc(generated, real), 0.92)


if __name__ == "__main__":
    unittest.main()
