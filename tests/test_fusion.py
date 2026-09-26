from __future__ import annotations

import unittest

from detecter.fusion import fused_ai_probability, fusion_verdict


class FusedProbabilityTests(unittest.TestCase):
    def test_high_scores_yield_high_probability(self):
        # Top-of-tuning ranks: CF logit at the cohort max, CuRe/UFD at 1.0.
        fused = fused_ai_probability(cf_score=5.0, cure_score=1.0, ufd_score=1.0)
        self.assertGreater(fused["probability"], 0.5)

    def test_low_scores_yield_low_probability(self):
        fused = fused_ai_probability(cf_score=-15.0, cure_score=0.0, ufd_score=0.0)
        self.assertLess(fused["probability"], 0.05)

    def test_missing_scores_use_neutral_rank(self):
        fused = fused_ai_probability(cf_score=-15.0)
        self.assertTrue(fused["partial"])
        self.assertEqual(fused["missing_scores"], ["cure_score", "ufd_score"])
        self.assertEqual(fused["ranks"]["cure_score"], 0.5)

    def test_scores_saturate_outside_reference_range(self):
        fused = fused_ai_probability(cf_score=1e6, cure_score=1e6, ufd_score=1e6)
        self.assertEqual(fused["ranks"]["cf_score"], 1.0)

    def test_all_scores_missing_raises(self):
        with self.assertRaises(ValueError):
            fused_ai_probability()


class FusionVerdictTests(unittest.TestCase):
    def test_confirmed_c2pa_claim_is_ai_evidence_confirmed(self):
        verdict = fusion_verdict(
            cf_score=-15.0,
            cure_score=0.0,
            ufd_score=0.0,
            c2pa={
                "ai_source_assertion": True,
                "confirmation_state": "cryptographically_valid",
            },
        )
        self.assertEqual(verdict["state"], "ai_evidence_confirmed")
        self.assertEqual(verdict["probability"], 1.0)

    def test_verified_synthid_is_ai_evidence_confirmed(self):
        verdict = fusion_verdict(
            cf_score=-15.0,
            synthid={"state": "detected", "automatically_verified": True},
        )
        self.assertEqual(verdict["state"], "ai_evidence_confirmed")

    def test_clearly_low_scores_are_no_ai_signal(self):
        verdict = fusion_verdict(cf_score=-15.0, cure_score=0.0, ufd_score=0.0)
        self.assertEqual(verdict["state"], "no_ai_signal_detected")
        self.assertIn("fused_probability_below_clear_band", verdict["reasons"])

    def test_mid_band_is_inconclusive(self):
        # Rank ~0.75 on each feature sits between the clear and likely bands.
        from detecter.fusion import _model

        ref = _model()["rank_reference"]
        mid = {
            f"{name}_score": ref[f"{name}_score"][int(len(ref[f"{name}_score"]) * 0.75)]
            for name in ("cf", "cure", "ufd")
        }
        verdict = fusion_verdict(**mid)
        self.assertEqual(verdict["state"], "inconclusive")

    def test_no_scores_is_inconclusive(self):
        verdict = fusion_verdict()
        self.assertEqual(verdict["state"], "inconclusive")
        self.assertIn("no_passive_scores", verdict["reasons"])

    def test_photo_kind_uses_stricter_threshold(self):
        verdict = fusion_verdict(
            cf_score=5.0, cure_score=1.0, ufd_score=1.0, image_kind="photo"
        )
        self.assertEqual(verdict["image_kind"], "photo")
        self.assertLess(verdict["threshold"], 0.71)


if __name__ == "__main__":
    unittest.main()
