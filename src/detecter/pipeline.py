"""Run the saved evaluation stages and report adoption evidence."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from .calibration import validate_config
from .evaluation import evaluate_records, read_jsonl
from .ledger import read_ledger

TARGET_FPR_UPPER = 0.001
TARGET_GENERATED_RATE = 0.9
CONFIDENCE = 0.95
_BETA_EPSILON = 1e-300


def one_sided_upper_bound(
    successes: int, total: int, *, confidence: float = CONFIDENCE
) -> float | None:
    """Return a one-sided 95% upper bound; use the exact zero-failure bound."""
    if total < 0 or successes < 0 or successes > total:
        raise ValueError("successes and total must describe a valid count")
    if total == 0:
        return None
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")
    alpha = 1.0 - confidence
    if successes == 0:
        return 1.0 - alpha ** (1.0 / total)
    if successes == total:
        return 1.0
    return _beta_inverse(confidence, successes + 1, total - successes)


def _beta_continued_fraction(a: float, b: float, x: float) -> float:
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    d = max(abs(d), _BETA_EPSILON) * (1.0 if d >= 0 else -1.0)
    d = 1.0 / d
    result = d
    for index in range(1, 201):
        step = 2.0 * index
        numerator = index * (b - index) * x / ((qam + step) * (a + step))
        d = 1.0 + numerator * d
        d = max(abs(d), _BETA_EPSILON) * (1.0 if d >= 0 else -1.0)
        c = 1.0 + numerator / c
        c = max(abs(c), _BETA_EPSILON) * (1.0 if c >= 0 else -1.0)
        d = 1.0 / d
        result *= d * c
        numerator = -(a + index) * (a + b + index) * x / ((a + step) * (a + step + 1.0))
        d = 1.0 + numerator * d
        d = max(abs(d), _BETA_EPSILON) * (1.0 if d >= 0 else -1.0)
        c = 1.0 + numerator / c
        c = max(abs(c), _BETA_EPSILON) * (1.0 if c >= 0 else -1.0)
        d = 1.0 / d
        delta = d * c
        result *= delta
        if abs(delta - 1.0) < 3e-14:
            break
    return result


def _beta_cdf(x: float, a: float, b: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    factor = math.exp(
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return factor * _beta_continued_fraction(a, b, x) / a
    return 1.0 - factor * _beta_continued_fraction(b, a, 1.0 - x) / b


def _beta_inverse(probability: float, a: int, b: int) -> float:
    low, high = 0.0, 1.0
    for _ in range(100):
        middle = (low + high) / 2.0
        if _beta_cdf(middle, float(a), float(b)) < probability:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def _metric_upper(metric: dict[str, Any]) -> dict[str, Any]:
    numerator = metric.get("numerator")
    denominator = metric.get("denominator")
    if not isinstance(numerator, int) or not isinstance(denominator, int):
        return {"upper": None, "passes": False, "status": "insufficient_data"}
    upper = one_sided_upper_bound(numerator, denominator)
    return {
        "successes": numerator,
        "total": denominator,
        "upper": upper,
        "confidence": CONFIDENCE,
        "method": "clopper_pearson_one_sided",
        "passes": upper is not None and upper <= TARGET_FPR_UPPER,
        "status": metric.get("status"),
    }


def _ledger_shape(
    rows: list[dict[str, Any]], split: str
) -> tuple[set[str], set[str], list[str]]:
    ids: set[str] = set()
    groups: set[str] = set()
    reasons: list[str] = []
    group_states: dict[str, tuple[Any, Any]] = {}
    all_ids: set[str] = set()
    all_hashes: set[str] = set()
    for row in rows:
        image_id, group = row.get("image_id"), row.get("source_group")
        image_hash = row.get("sha256")
        if not isinstance(image_id, str) or not image_id or image_id in all_ids:
            reasons.append("ledger_duplicate_or_missing_image_id")
        if isinstance(image_id, str) and image_id:
            all_ids.add(image_id)
        if (
            not isinstance(image_hash, str)
            or not image_hash
            or image_hash in all_hashes
        ):
            reasons.append("ledger_duplicate_or_missing_sha256")
        if isinstance(image_hash, str) and image_hash:
            all_hashes.add(image_hash)
        if not isinstance(group, str) or not group:
            reasons.append("ledger_source_group_missing")
        if isinstance(group, str) and group:
            state = (row.get("label"), row.get("split"))
            if group in group_states and group_states[group] != state:
                reasons.append("source_group_crosses_label_or_split")
            group_states[group] = state
        if row.get("split") != split:
            continue
        if isinstance(image_id, str):
            ids.add(image_id)
        if isinstance(group, str):
            groups.add(group)
    return ids, groups, sorted(set(reasons))


def _comparison_stage(
    records: list[dict[str, Any]] | None,
    rows_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if records is None:
        return {"status": "insufficient", "reason": "comparison_not_provided"}
    by_id: dict[str, set[str]] = {}
    invalid: list[str] = []
    for row in records:
        image_id, model = row.get("image_id"), row.get("model")
        if isinstance(image_id, str) and isinstance(model, str):
            by_id.setdefault(image_id, set()).add(model)
            ledger_row = rows_by_id.get(image_id)
            if ledger_row is None or row.get("sha256") != ledger_row.get("sha256"):
                invalid.append("comparison_hash_mismatch")
            if row.get("status") != "ok":
                invalid.append("comparison_model_failed")
    required = {"ufd", "community-forensics-384"}
    complete = (
        all(by_id.get(image_id, set()) >= required for image_id in rows_by_id)
        and not invalid
    )
    return {
        "status": "ok" if complete else "insufficient",
        "image_count": len(by_id),
        "required_models": sorted(required),
        "reason": None
        if complete
        else (sorted(set(invalid)) or "comparison_missing_model_or_image"),
    }


def _preprocessing_stage(
    records: list[dict[str, Any]] | None,
    rows_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if records is None:
        return {
            "status": "insufficient",
            "reason": "preprocessing_conditions_not_provided",
        }
    expected = {
        ("jpeg", 95),
        ("jpeg", 85),
        ("jpeg", 75),
        ("resize", 1024),
        ("resize", 512),
    }
    seen: set[tuple[Any, Any]] = set()
    seen_by_source: dict[str, set[tuple[Any, Any]]] = {}
    invalid: list[str] = []
    for row in records:
        condition = row.get("condition") if isinstance(row, dict) else None
        source_id = row.get("source_image_id") if isinstance(row, dict) else None
        source_hash = row.get("source_sha256") if isinstance(row, dict) else None
        parent = rows_by_id.get(source_id)
        if parent is None or parent.get("sha256") != source_hash:
            invalid.append("preprocessing_source_hash_mismatch")
        if row.get("status") not in {"created", "duplicate", "unchanged"}:
            invalid.append("preprocessing_condition_failed")
        if isinstance(condition, dict):
            key = (
                condition.get("operation"),
                condition.get("jpeg_quality") or condition.get("long_side"),
            )
            seen.add(key)
            if isinstance(source_id, str):
                seen_by_source.setdefault(source_id, set()).add(key)
    missing = sorted(expected - seen, key=str)
    incomplete_sources = sorted(
        source_id
        for source_id in rows_by_id
        if not expected <= seen_by_source.get(source_id, set())
    )
    if incomplete_sources:
        invalid.append("preprocessing_conditions_missing_for_image")
    return {
        "status": "ok" if not missing and not invalid else "insufficient",
        "condition_count": len(records),
        "missing_conditions": [list(item) for item in missing],
        "incomplete_source_count": len(incomplete_sources),
        "reason": None
        if not missing and not invalid
        else sorted(set(invalid)) or "preprocessing_condition_missing",
    }


def _base_report() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "insufficient_evidence",
        "criteria": {},
        "stages": {},
        "unverified": [],
        "adoption": {"status": "evidence_insufficient", "decision_applied": False},
    }


def run_pipeline(
    ledger: list[dict[str, Any]],
    decision_config: dict[str, Any],
    *,
    measurements: list[dict[str, Any]] | None = None,
    decisions: list[dict[str, Any]] | None = None,
    comparisons: list[dict[str, Any]] | None = None,
    derived_conditions: list[dict[str, Any]] | None = None,
    synthid: list[dict[str, Any]] | None = None,
    split: str = "evaluation",
    unit: str = "source_group",
) -> dict[str, Any]:
    report = _base_report()
    if split != "evaluation":
        report["unverified"] = ["final_evaluation_requires_evaluation_split"]
        return report
    if unit != "source_group":
        report["unverified"] = ["pipeline_requires_source_group_unit"]
        return report
    try:
        validate_config(decision_config, usage="evaluation")
    except ValueError as error:
        report["status"] = (
            "not_met"
            if decision_config.get("status") == "unmet"
            else "insufficient_evidence"
        )
        report["adoption"] = {
            "status": "not_met"
            if decision_config.get("status") == "unmet"
            else "evidence_insufficient",
            "decision_applied": False,
            "reason": f"decision_config_invalid: {error}",
        }
        report["unverified"] = ["decision_config_invalid"]
        return report

    ids, groups, shape_reasons = _ledger_shape(ledger, split)
    calibration = decision_config.get("calibration_images", [])
    calibration_ids = {
        row.get("image_id") for row in calibration if isinstance(row, dict)
    }
    calibration_groups = {
        row.get("source_group") for row in calibration if isinstance(row, dict)
    }
    calibration_hashes = {
        row.get("sha256") for row in calibration if isinstance(row, dict)
    }
    final_hashes = {row.get("sha256") for row in ledger if row.get("split") == split}
    leakage = sorted(
        (ids & calibration_ids)
        | (groups & calibration_groups)
        | (final_hashes & calibration_hashes),
        key=str,
    )
    report["stages"]["ledger"] = {
        "status": "ok" if not shape_reasons else "invalid",
        "image_count": len(ids),
        "source_group_count": len(groups),
        "split": split,
        "reasons": shape_reasons,
    }
    rows_by_id = {
        row["image_id"]: row
        for row in ledger
        if row.get("split") == split and isinstance(row.get("image_id"), str)
    }
    report["stages"]["preprocessing"] = _preprocessing_stage(
        derived_conditions, rows_by_id
    )
    report["stages"]["comparison"] = _comparison_stage(comparisons, rows_by_id)
    if leakage:
        report["unverified"].append("final_evaluation_overlaps_calibration")
    if shape_reasons:
        report["unverified"].extend(shape_reasons)
    if report["stages"]["preprocessing"]["status"] != "ok":
        report["unverified"].append("preprocessing_conditions_not_provided")
    if report["stages"]["comparison"]["status"] != "ok":
        report["unverified"].append("model_comparison_incomplete")
    if synthid is None:
        report["unverified"].append("synthid_manual_not_registered")

    if measurements is None:
        measurements = []
        report["unverified"].append("measurements_missing")
    if decisions is None and measurements:
        from .cli import apply_decision

        measurement_by_id = {row.get("image_id"): row for row in measurements}
        decisions = []
        for row in ledger:
            if row.get("split") != split:
                continue
            measurement = measurement_by_id.get(row.get("image_id"))
            if measurement is None:
                continue
            generated = apply_decision(
                {
                    "image_id": row.get("image_id"),
                    "media": {"sha256": row.get("sha256")},
                    "c2pa": measurement.get("c2pa", {}),
                    "universal_fake_detect": measurement,
                },
                decision_config,
            )
            decisions.append(
                {
                    **generated,
                    "image_id": row.get("image_id"),
                    "sha256": row.get("sha256"),
                    **{
                        key: measurement.get(key)
                        for key in (
                            "model",
                            "model_version",
                            "weights_version",
                            "preprocessing_version",
                        )
                    },
                }
            )
        decision_status = "generated_from_measurements"
    elif decisions is not None:
        decision_status = "loaded"
    else:
        decisions = []
        decision_status = "insufficient"
    expected_condition = tuple(
        decision_config.get(key)
        for key in (
            "model",
            "model_version",
            "weights_version",
            "preprocessing_version",
        )
    )
    decision_reasons: list[str] = []
    for decision in decisions:
        if decision.get("config_id") != decision_config.get("config_id"):
            decision_reasons.append("decision_config_id_mismatch")
        actual_condition = tuple(
            decision.get(key)
            for key in (
                "model",
                "model_version",
                "weights_version",
                "preprocessing_version",
            )
        )
        if actual_condition != expected_condition:
            decision_reasons.append("decision_condition_mismatch")
    if decision_reasons:
        decision_status = "invalid"
        report["unverified"].extend(decision_reasons)
    report["stages"]["decision"] = {
        "status": decision_status,
        "count": len(decisions),
        "reasons": sorted(set(decision_reasons)),
    }

    try:
        evaluation = evaluate_records(
            ledger,
            measurements,
            decisions,
            unit=unit,
            split=split,
        )
    except ValueError as error:
        evaluation = None
        report["unverified"].append(f"evaluation_invalid: {error}")
    report["stages"]["evaluation"] = (
        {"status": "ok", "report": evaluation}
        if evaluation is not None
        else {"status": "insufficient", "reason": "evaluation_records_invalid"}
    )

    processing_complete = (
        report["stages"]["preprocessing"]["status"] == "ok"
        and report["stages"]["comparison"]["status"] == "ok"
    )
    if (
        evaluation is None
        or not ids
        or leakage
        or shape_reasons
        or not processing_complete
    ):
        report["status"] = "insufficient_evidence"
    else:
        fpr = evaluation["metrics"]["false_positive_rate"]
        generated = evaluation["metrics"]["generated_detection_rate"]
        fpr_upper = _metric_upper(fpr)
        generated_rate = (
            generated.get("rate") if generated.get("status") == "measured" else None
        )
        real_rows = fpr.get("target_count", 0)
        if real_rows < 3000:
            report["unverified"].append("fewer_than_3000_independent_real_images")
        if not any(row.get("generator") for row in ledger if row.get("split") == split):
            report["unverified"].append("generator_breakdown_not_provided")
        if not any(row.get("camera") for row in ledger if row.get("split") == split):
            report["unverified"].append("camera_breakdown_not_provided")
        if not any(
            row.get("label") == "edited" for row in ledger if row.get("split") == split
        ):
            report["unverified"].append("partial_edit_scope_not_evaluated")
        report["criteria"] = {
            "false_positive_upper_bound": fpr_upper,
            "generated_detection_rate": {
                "numerator": generated.get("numerator"),
                "denominator": generated.get("denominator"),
                "rate": generated_rate,
                "target": TARGET_GENERATED_RATE,
                "passes": generated_rate is not None
                and generated_rate >= TARGET_GENERATED_RATE,
                "status": generated.get("status"),
            },
        }
        report["fixed_reference"] = {
            "successes": 0,
            "total": 3000,
            "upper_bound": one_sided_upper_bound(0, 3000),
            "target": TARGET_FPR_UPPER,
        }
        synthetic = any(
            str(row.get("source", "")).lower().startswith("synthetic")
            for row in ledger
            if row.get("split") == split
        )
        if synthetic and ids:
            report["unverified"].append("synthetic_data_not_performance_evidence")
        if fpr.get("excluded_count", 0):
            report["unverified"].append("real_measurement_missing_or_unresolved")
        if (
            fpr_upper["passes"]
            and report["criteria"]["generated_detection_rate"]["passes"]
            and real_rows >= 3000
            and not fpr.get("excluded_count", 0)
            and report["stages"]["decision"]["status"] != "invalid"
            and not synthetic
            and processing_complete
        ):
            report["status"] = "achieved"
        elif (
            fpr_upper["upper"] is None
            or generated_rate is None
            or fpr.get("excluded_count", 0)
            or real_rows < 3000
            or synthetic
            or report["stages"]["decision"]["status"] == "invalid"
            or not processing_complete
        ):
            report["status"] = "insufficient_evidence"
        else:
            report["status"] = "not_met"
    report["unverified"] = sorted(set(report["unverified"]))
    report["adoption"] = {
        "status": {"achieved": "adoptable", "not_met": "not_met"}.get(
            report["status"], "evidence_insufficient"
        ),
        "decision_applied": report["stages"].get("decision", {}).get("status")
        in {"loaded", "generated_from_measurements"},
        "performance_status": report["status"],
    }
    return report


def _write_report(path: Path, report: dict[str, Any]) -> None:
    text = (
        json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
    )
    if str(path) == "-":
        print(text, end="")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as stream:
            stream.write(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="全経路の保存済み結果を評価し、採用可否を報告します"
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--decision-config", type=Path, required=True)
    parser.add_argument("--measurements", type=Path)
    parser.add_argument("--decisions", type=Path)
    parser.add_argument("--comparison", type=Path)
    parser.add_argument("--derived-conditions", type=Path)
    parser.add_argument(
        "--derive-directory",
        type=Path,
        help="加工を実行して派生画像を保存するディレクトリ",
    )
    parser.add_argument(
        "--run-ufd", action="store_true", help="台帳画像をUFDで計測する"
    )
    parser.add_argument(
        "--run-comparison",
        action="store_true",
        help="Community ForensicsとUFDを計測する",
    )
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--device", choices=("cpu", "auto", "cuda"), default="cpu")
    parser.add_argument("--synthid", type=Path)
    parser.add_argument("--split", default="evaluation")
    parser.add_argument(
        "--unit", choices=("image", "source_group"), default="source_group"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        ledger = read_ledger(args.ledger)
        config = json.loads(args.decision_config.read_text(encoding="utf-8"))
        effective_ledger = ledger
        measurements = read_jsonl(args.measurements) if args.measurements else None
        decisions = read_jsonl(args.decisions) if args.decisions else None
        comparisons = read_jsonl(args.comparison) if args.comparison else None
        derived = (
            read_jsonl(args.derived_conditions) if args.derived_conditions else None
        )
        synthid = read_jsonl(args.synthid) if args.synthid else None
        if args.derive_directory is not None:
            from .derive_jpeg import derive_images

            derived_rows, derived = derive_images(args.ledger, args.derive_directory)
            effective_ledger = [*ledger, *derived_rows]
        measurement_inputs = [
            {
                "image_id": row.get("image_id"),
                "path": row.get("path"),
                "sha256": row.get("sha256"),
                "source_sha256": row.get("source_sha256", row.get("sha256")),
                "history": row.get("history", []),
            }
            for row in effective_ledger
            if row.get("split") == args.split
        ]
        if args.run_ufd:
            from .ufd_batch import measure_batch

            measurements = measure_batch(
                measurement_inputs, cache_dir=args.cache_dir, device=args.device
            )
        if args.run_comparison:
            from .comparison import compare_records

            comparisons = compare_records(
                measurement_inputs, cache_dir=args.cache_dir, device=args.device
            )
            if measurements is None:
                measurements = [row for row in comparisons if row.get("model") == "ufd"]
        report = run_pipeline(
            effective_ledger,
            config,
            measurements=measurements,
            decisions=decisions,
            comparisons=comparisons,
            derived_conditions=derived,
            synthid=synthid,
            split=args.split,
            unit=args.unit,
        )
        _write_report(args.output, report)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        report = _base_report()
        report["unverified"] = [f"pipeline_input_invalid: {error}"]
        report["adoption"]["reason"] = str(error)
        try:
            _write_report(args.output, report)
        except OSError:
            print(str(error), file=sys.stderr)
            return 2
        return 2
    return {"achieved": 0, "insufficient_evidence": 0, "not_met": 1}.get(
        report["status"], 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
