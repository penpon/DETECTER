"""Logistic fusion of CF384/CuRe/UFD raw scores into a base AI probability."""

from __future__ import annotations

import math
from typing import Any

MODEL = "base-ai-probability"
MODEL_VERSION = "logistic-v1"
WEIGHTS_VERSION = "cf384+cure+ufd-logistic-v1"
PREPROCESSING_VERSION = "raw-scores-v1"
CALIBRATION_SPLIT = "tuning"

WEIGHTS = {
    "cf_score": 0.5185,
    "cure_score": 2.7269,
    "ufd_score": -3.0123,
}
BIAS = 3.5753


def _finite_score(value: Any, name: str) -> float | None:
    if value is None:
        return None
    score = float(value)
    if not math.isfinite(score):
        raise ValueError(f"{name} must be a finite number")
    return score


def calibrated_ai_probability(
    cf_score: float | None = None,
    cure_score: float | None = None,
    ufd_score: float | None = None,
    *,
    weights: dict[str, float] | None = None,
    bias: float = BIAS,
) -> dict[str, Any]:
    """Combine the three passive scores into P(AI) in [0.0, 1.0].

    Missing scores are dropped from the logit (a neutral zero contribution)
    and reported via ``partial`` / ``missing_scores``.
    """
    scores = {
        "cf_score": _finite_score(cf_score, "cf_score"),
        "cure_score": _finite_score(cure_score, "cure_score"),
        "ufd_score": _finite_score(ufd_score, "ufd_score"),
    }
    if all(score is None for score in scores.values()):
        raise ValueError("at least one score is required")
    coefficients = WEIGHTS if weights is None else dict(weights)
    logit = float(bias) + sum(
        coefficients[name] * score
        for name, score in scores.items()
        if score is not None
    )
    # Stable sigmoid; exp(logit) overflows near logit > 709.
    probability = (
        1.0 / (1.0 + math.exp(-logit))
        if logit >= 0
        else ((e := math.exp(logit)) / (1.0 + e))
    )
    return {
        "probability": probability,
        "logit": logit,
        "weights": coefficients,
        "bias": float(bias),
        "missing_scores": [name for name, score in scores.items() if score is None],
        "partial": any(score is None for score in scores.values()),
        "model_condition": {
            "model": MODEL,
            "model_version": MODEL_VERSION,
            "weights_version": WEIGHTS_VERSION,
            "preprocessing_version": PREPROCESSING_VERSION,
            "calibration_split": CALIBRATION_SPLIT,
        },
    }
