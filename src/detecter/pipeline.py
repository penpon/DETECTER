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
    # Wilson's one-sided normal bound is a stable stdlib fallback for x > 0.
    z = 1.6448536269514722
    p = successes / total
    denominator = 1.0 + z * z / total
    centre = p + z * z / (2.0 * total)
    spread = z * math.sqrt(p * (1.0 - p) / total + z * z / (4.0 * total * total))
    return min(1.0, (centre + spread) / denominator)


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
        "method": "clopper_pearson_zero_failure_or_wilson_one_sided",
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
    for row in rows:
        image_id, group = row.get("image_id"), row.get("source_group")
        if not isinstance(image_id, str) or not image_id or image_id in ids:
            reasons.append("ledger_duplicate_or_missing_image_id")
        if not isinstance(group, str) or not group:
            reasons.append("ledger_source_group_missing")
        if row.get("split") != split:
            continue
        if isinstance(image_id, str):
            ids.add(image_id)
        if isinstance(group, str):
            groups.add(group)
            state = (row.get("label"), row.get("split"))
            if group in group_states and group_states[group] != state:
                reasons.append("source_group_crosses_label_or_split")
            group_states[group] = state
    return ids, groups, sorted(set(reasons))


def _comparison_stage(
    records: list[dict[str, Any]] | None, ids: set[str]
) -> dict[str, Any]:
    if records is None:
        return {"status": "insufficient", "reason": "comparison_not_provided"}
    by_id: dict[str, set[str]] = {}
    for row in records:
        image_id, model = row.get("image_id"), row.get("model")
        if isinstance(image_id, str) and isinstance(model, str):
            by_id.setdefault(image_id, set()).add(model)
    required = {"ufd", "community-forensics-384"}
    complete = all(by_id.get(image_id, set()) >= required for image_id in ids)
    return {
        "status": "ok" if complete else "insufficient",
        "image_count": len(by_id),
        "required_models": sorted(required),
        "reason": None if complete else "comparison_missing_model_or_image",
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
    leakage = sorted((ids & calibration_ids) | (groups & calibration_groups))
    report["stages"]["ledger"] = {
        "status": "ok" if not shape_reasons else "invalid",
        "image_count": len(ids),
        "source_group_count": len(groups),
        "split": split,
        "reasons": shape_reasons,
    }
    report["stages"]["preprocessing"] = (
        {"status": "ok", "condition_count": len(derived_conditions)}
        if derived_conditions is not None
        else {
            "status": "insufficient",
            "reason": "preprocessing_conditions_not_provided",
        }
    )
    report["stages"]["comparison"] = _comparison_stage(comparisons, ids)
    if leakage:
        report["unverified"].append("final_evaluation_overlaps_calibration")
    if shape_reasons:
        report["unverified"].extend(shape_reasons)
    if derived_conditions is None:
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
    report["stages"]["decision"] = {"status": decision_status, "count": len(decisions)}

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

    if evaluation is None or not ids or leakage or shape_reasons:
        report["status"] = "insufficient_evidence"
    else:
        fpr = evaluation["metrics"]["false_positive_rate"]
        generated = evaluation["metrics"]["generated_detection_rate"]
        fpr_upper = _metric_upper(fpr)
        generated_rate = (
            generated.get("rate") if generated.get("status") == "measured" else None
        )
        real_rows = sum(
            row.get("label") == "real" for row in ledger if row.get("split") == split
        )
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
        if (
            fpr_upper["passes"]
            and report["criteria"]["generated_detection_rate"]["passes"]
        ):
            report["status"] = "achieved"
        elif (
            fpr_upper["upper"] is None
            or generated_rate is None
            or fpr.get("excluded_count", 0)
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
        not in {"insufficient"},
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
        measurements = read_jsonl(args.measurements) if args.measurements else None
        decisions = read_jsonl(args.decisions) if args.decisions else None
        comparisons = read_jsonl(args.comparison) if args.comparison else None
        derived = (
            read_jsonl(args.derived_conditions) if args.derived_conditions else None
        )
        synthid = read_jsonl(args.synthid) if args.synthid else None
        report = run_pipeline(
            ledger,
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
