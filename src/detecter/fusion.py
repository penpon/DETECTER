"""Calibrated statistical fusion of passive scores into a 4-state verdict.

Replaces the Jev System One composition (#67): Jev handles language
reasoning well but not numeric precision, so the final verdict comes from a
logistic model fit on group-aggregated tuning scores with isotonic-style
calibration embedded in the rank features. Jev remains available via
``--jev`` for ablation comparisons.

Inputs are the three passive raw scores (CF384 logit, CuRe probability,
UFD score). Each score is mapped to its empirical rank inside the tuning
cohort (``data/fusion_model.json``), so the linear model is scale-free and
a score outside the tuning range saturates at 0.0 / 1.0 rank instead of
extrapolating. Missing scores use the neutral rank 0.5.

Thresholds are the operating points selected on the tuning groups at the
FPR=0.1% budget (``floor(N_real * 0.001)`` allowed false positives), with a
separate operating point for EXIF-verified photos. See
``docs/cohort-issue67-fusion.md`` for the fit and comparison numbers.
"""

from __future__ import annotations

import json
import math
from bisect import bisect_left
from collections.abc import Mapping
from functools import lru_cache
from importlib import resources
from typing import Any

MODEL = "fusion"
MODEL_VERSION = "rank-logistic-v1"
RANKS_RESOURCE = "fusion_model.json"

DECISION_STATES = (
    "ai_evidence_confirmed",
    "ai_likely",
    "inconclusive",
    "no_ai_signal_detected",
)

_FEATURES = ("cf_score", "cure_score", "ufd_score")
_NEUTRAL_RANK = 0.5


@lru_cache(maxsize=1)
def _model() -> dict[str, Any]:
    data = resources.files("detecter").joinpath(f"data/{RANKS_RESOURCE}")
    return json.loads(data.read_text(encoding="utf-8"))


def _finite(value: Any, name: str) -> float | None:
    if value is None:
        return None
    score = float(value)
    if not math.isfinite(score):
        raise ValueError(f"{name} must be a finite number")
    return score


def _rank(feature: str, value: float | None) -> float:
    if value is None:
        return _NEUTRAL_RANK
    reference = _model()["rank_reference"][feature]
    return bisect_left(reference, value) / len(reference)


def _sigmoid(logit: float) -> float:
    return (
        1.0 / (1.0 + math.exp(-logit))
        if logit >= 0
        else ((e := math.exp(logit)) / (1.0 + e))
    )


def fused_ai_probability(
    *,
    cf_score: float | None = None,
    cure_score: float | None = None,
    ufd_score: float | None = None,
) -> dict[str, Any]:
    """Combine passive scores into a calibrated P(AI) in [0.0, 1.0]."""
    raw = {
        "cf_score": _finite(cf_score, "cf_score"),
        "cure_score": _finite(cure_score, "cure_score"),
        "ufd_score": _finite(ufd_score, "ufd_score"),
    }
    if all(score is None for score in raw.values()):
        raise ValueError("at least one score is required")
    ranks = {name: _rank(name, score) for name, score in raw.items()}
    logit = _model()["bias"] + sum(
        _model()["weights"][name] * ranks[name] for name in _FEATURES
    )
    probability = _sigmoid(logit)
    return {
        "probability": probability,
        "logit": logit,
        "ranks": ranks,
        "missing_scores": [name for name, score in raw.items() if score is None],
        "partial": any(score is None for score in raw.values()),
        "model_condition": {
            "model": MODEL,
            "model_version": MODEL_VERSION,
            "calibration_split": "tuning",
        },
    }


def fusion_verdict(
    *,
    cf_score: float | None = None,
    cure_score: float | None = None,
    ufd_score: float | None = None,
    c2pa: Mapping[str, Any] | None = None,
    synthid: Mapping[str, Any] | None = None,
    image_kind: str = "unknown",
) -> dict[str, Any]:
    """Map the fused probability to the shared 4-state verdict + reasons.

    ``image_kind`` selects the operating point: ``photo`` uses the stricter
    threshold fitted on EXIF-verified real photos only.
    """
    c2pa = c2pa or {}
    synthid = synthid or {}
    reasons: list[str] = []

    confirmed_ai_claim = bool(
        c2pa.get("ai_source_assertion") or c2pa.get("ai_disclosure_assertion")
    ) and c2pa.get("confirmation_state") in {"trusted", "cryptographically_valid"}
    if confirmed_ai_claim:
        return {
            "status": "ok",
            "state": "ai_evidence_confirmed",
            "probability": 1.0,
            "image_kind": image_kind,
            "reasons": ["c2pa_confirmed_ai_claim"],
        }
    if synthid.get("state") == "detected" and synthid.get("automatically_verified"):
        return {
            "status": "ok",
            "state": "ai_evidence_confirmed",
            "probability": 1.0,
            "image_kind": image_kind,
            "reasons": ["synthid_detected"],
        }

    try:
        fused = fused_ai_probability(
            cf_score=cf_score, cure_score=cure_score, ufd_score=ufd_score
        )
    except ValueError:
        return {
            "status": "ok",
            "state": "inconclusive",
            "probability": None,
            "image_kind": image_kind,
            "reasons": ["no_passive_scores"],
        }

    probability = fused["probability"]
    thresholds = _model()["thresholds"]
    point = thresholds.get(image_kind) or thresholds["default"]
    likely_at = point["ai_likely"]
    clear_below = point["no_ai_signal_below"]

    if probability >= likely_at:
        state = "ai_likely"
        reasons.append("fused_probability_above_threshold")
    elif probability < clear_below and not fused["partial"]:
        state = "no_ai_signal_detected"
        reasons.append("fused_probability_below_clear_band")
    else:
        state = "inconclusive"
        if fused["partial"]:
            reasons.append("partial_scores")
        if probability >= clear_below:
            reasons.append("fused_probability_in_hold_band")

    return {
        "status": "ok",
        "state": state,
        "probability": round(probability, 6),
        "threshold": likely_at,
        "image_kind": image_kind,
        "reasons": sorted(set(reasons)),
        "fusion": fused,
    }
