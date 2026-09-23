"""Compare candidates on tuning data, freeze one, and evaluate it once on final data."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from .calibration import calibrate_records, config_id_for, validate_config
from .evaluation import CONDITION_FIELDS, condition, evaluate_records, read_jsonl
from .ledger import read_ledger
from .pipeline import run_pipeline

SCHEMA_VERSION = 1
SELECTION_POLICY = (
    "meet_tuning_targets; highest_generated_detection; "
    "lowest_hold; lowest_failure; highest_threshold; config_id"
)


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def selection_id_for(selection: dict[str, Any]) -> str:
    """Content identifier; omit the identifier itself when hashing JSON."""
    return _digest(
        {key: value for key, value in selection.items() if key != "selection_id"}
    )


def _tuning_decisions(
    ledger: list[dict[str, Any]],
    measurements: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    from .cli import apply_decision

    measurement_by_id = {row["image_id"]: row for row in measurements}
    decisions = []
    for row in ledger:
        measurement = measurement_by_id[row["image_id"]]
        generated = apply_decision(
            {
                "image_id": row["image_id"],
                "media": {"sha256": row["sha256"]},
                "c2pa": measurement.get("c2pa", {}),
                "universal_fake_detect": measurement,
            },
            config,
        )
        decisions.append(
            {
                **generated,
                "image_id": row["image_id"],
                "sha256": row["sha256"],
            }
        )
    return decisions


def _summarize_candidate(
    name: str,
    ledger: list[dict[str, Any]],
    measurements: list[dict[str, Any]],
) -> dict[str, Any]:
    config = calibrate_records(ledger, measurements)
    decisions = _tuning_decisions(ledger, measurements, config)
    tuning = evaluate_records(
        ledger, measurements, decisions, unit="source_group", split="tuning"
    )
    metrics = tuning["metrics"]
    summary = {
        "name": name,
        "condition": dict(zip(CONDITION_FIELDS, condition(config), strict=True)),
        "preprocessing": deepcopy(measurements[0].get("preprocessing")),
        "threshold": config["threshold"],
        "comparison": config["comparison"],
        "config_id": config["config_id"],
        "calibration_id": config["calibration_id"],
        "status": config["status"],
        "meets_tuning_targets": config["status"] == "candidate",
        "tuning_metrics": {
            key: {
                "numerator": metrics[key]["numerator"],
                "denominator": metrics[key]["denominator"],
                "rate": metrics[key]["rate"],
                "status": metrics[key]["status"],
            }
            for key in (
                "false_positive_rate",
                "generated_detection_rate",
                "hold_rate",
                "failure_rate",
            )
        },
        "config": deepcopy(config),
    }
    return summary


def _rank_key(summary: dict[str, Any]) -> tuple[Any, ...]:
    metrics = summary["tuning_metrics"]
    return (
        -metrics["generated_detection_rate"]["numerator"],
        metrics["hold_rate"]["numerator"],
        metrics["failure_rate"]["numerator"],
        -summary["threshold"],
        summary["config_id"],
    )


def run_selection(
    tuning_ledger: list[dict[str, Any]],
    measurements_by_candidate: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Calibrate every candidate on the same tuning groups and freeze one choice."""
    if not measurements_by_candidate:
        raise ValueError("at least one candidate is required")
    summaries = [
        _summarize_candidate(name, tuning_ledger, measurements_by_candidate[name])
        for name in sorted(measurements_by_candidate)
    ]
    eligible = [row for row in summaries if row["meets_tuning_targets"]]
    chosen = min(eligible, key=_rank_key) if eligible else None
    selection: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "selection_policy": SELECTION_POLICY,
        "split": "tuning",
        "unit": "source_group",
        "tuning_source_groups": sorted({row["source_group"] for row in tuning_ledger}),
        "tuning_image_count": len(tuning_ledger),
        "candidates": summaries,
        "selected": None
        if chosen is None
        else {
            "name": chosen["name"],
            "config_id": chosen["config_id"],
            "tuning_metrics": deepcopy(chosen["tuning_metrics"]),
            "config": deepcopy(chosen["config"]),
        },
        "status": "selected" if chosen is not None else "no_candidate",
    }
    return {"selection_id": selection_id_for(selection), **selection}


def _selection_error(reason: str, selection: dict[str, Any] | None) -> dict[str, Any]:
    record = selection if isinstance(selection, dict) else {}
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "insufficient_evidence",
        "selection": {
            "selection_id": record.get("selection_id"),
            "status": record.get("status"),
            "reselected_after_final": False,
        },
        "unverified": [reason],
        "production_config_replaced": False,
        "adoption": {
            "status": "evidence_insufficient",
            "decision_applied": False,
            "reason": reason,
        },
    }


def run_final(
    selection: dict[str, Any],
    final_ledger: list[dict[str, Any]],
    *,
    measurements: list[dict[str, Any]] | None = None,
    decisions: list[dict[str, Any]] | None = None,
    comparisons: list[dict[str, Any]] | None = None,
    derived_conditions: list[dict[str, Any]] | None = None,
    synthid: list[dict[str, Any]] | None = None,
    required_generators: dict[str, int] | None = None,
    reselected_after_final: bool = False,
) -> dict[str, Any]:
    """Evaluate the frozen selection once on final data; never reselect here."""
    if not isinstance(selection, dict) or selection.get(
        "selection_id"
    ) != selection_id_for({k: v for k, v in selection.items() if k != "selection_id"}):
        return _selection_error("selection_record_invalid", selection)
    selected = selection.get("selected")
    if selection.get("status") != "selected" or not isinstance(selected, dict):
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "no_candidate",
            "selection": {
                "selection_id": selection.get("selection_id"),
                "selection_policy": selection.get("selection_policy"),
                "status": "no_candidate",
                "candidates": selection.get("candidates", []),
                "reselected_after_final": bool(reselected_after_final),
            },
            "unverified": ["tuning_produced_no_candidate_meeting_targets"],
            "production_config_replaced": False,
            "adoption": {
                "status": "no_candidate",
                "decision_applied": False,
                "reason": "no tuning candidate met the targets; "
                "unmet settings are not saved as validated or production",
            },
        }
    frozen = selected.get("config")
    try:
        if not isinstance(frozen, dict):
            raise ValueError("missing frozen config")  # noqa: TRY004 -- invalid selection record
        validate_config(frozen, usage="evaluation")
        if frozen.get("config_id") != config_id_for(frozen):
            raise ValueError("frozen config_id does not match config contents")
        if selected.get("config_id") != frozen.get("config_id"):
            raise ValueError("frozen config does not match the selection record")
    except ValueError as error:
        return _selection_error(f"frozen_config_invalid: {error}", selection)
    expected = tuple(frozen.get(key) for key in CONDITION_FIELDS)
    for row in measurements or []:
        if condition(row) != expected:
            report = _selection_error("final_condition_mismatch", selection)
            report["selection"]["candidate"] = selected.get("name")
            return report
    report = run_pipeline(
        final_ledger,
        frozen,
        measurements=measurements,
        decisions=decisions,
        comparisons=comparisons,
        derived_conditions=derived_conditions,
        synthid=synthid,
        split="evaluation",
        unit="source_group",
        required_generators=required_generators,
    )
    report["selection"] = {
        "selection_id": selection["selection_id"],
        "selection_policy": selection["selection_policy"],
        "candidate": selected.get("name"),
        "config_id": frozen.get("config_id"),
        "condition": dict(zip(CONDITION_FIELDS, expected, strict=True)),
        "tuning_metrics": deepcopy(selected.get("tuning_metrics")),
        "reselected_after_final": bool(reselected_after_final),
    }
    report["production_config_replaced"] = False
    if reselected_after_final:
        reason = "reselected_after_final:requires_fresh_unused_data"
        report["status"] = "insufficient_evidence"
        report["unverified"] = sorted(set(report.get("unverified", [])) | {reason})
        report["adoption"] = {
            "status": "evidence_insufficient",
            "decision_applied": report.get("adoption", {}).get(
                "decision_applied", False
            ),
            "performance_status": "insufficient_evidence",
            "reason": "candidates or thresholds were reselected after seeing "
            "final evaluation results; this final evaluation is not adoption "
            "evidence and fresh unused data is required",
        }
    return report


def _parse_candidates(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        name, separator, path = value.partition("=")
        if not separator or not name.strip() or not path.strip():
            raise ValueError(f"invalid --candidate: {value!r}")
        if name in result:
            raise ValueError(f"duplicate --candidate: {name!r}")
        result[name] = Path(path)
    if not result:
        raise ValueError("at least one --candidate NAME=PATH is required")
    return result


def _parse_required_generators(values: list[str]) -> dict[str, int]:
    required: dict[str, int] = {}
    for value in values:
        name, separator, count = value.partition(":")
        if not separator or not name.strip():
            raise ValueError(f"invalid --required-generator: {value!r}")
        try:
            minimum = int(count)
        except ValueError:
            raise ValueError(f"invalid --required-generator: {value!r}") from None
        if minimum < 0:
            raise ValueError(f"invalid --required-generator: {value!r}")
        required[name] = minimum
    return required


def _write(path: Path, payload: dict[str, Any]) -> None:
    text = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
    )
    if str(path) == "-":
        print(text, end="")
        return
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        stream.write(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="調整用データで候補を選び、固定した設定を最終評価で一度だけ評価します"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    select = commands.add_parser(
        "select", help="調整用データで候補としきい値を固定します"
    )
    select.add_argument("--tuning-ledger", type=Path, required=True)
    select.add_argument(
        "--candidate",
        action="append",
        default=[],
        metavar="NAME=MEASUREMENTS",
        help="候補名と調整用計測JSON Lines（例: ufd=tuning-ufd.jsonl）。繰り返し指定可。",
    )
    select.add_argument("--output", type=Path, required=True)
    finalize = commands.add_parser(
        "finalize", help="固定した設定で最終評価用データを一度評価します"
    )
    finalize.add_argument("--ledger", type=Path, required=True)
    finalize.add_argument("--selection", type=Path, required=True)
    finalize.add_argument("--measurements", type=Path)
    finalize.add_argument("--decisions", type=Path)
    finalize.add_argument("--comparison", type=Path)
    finalize.add_argument("--derived-conditions", type=Path)
    finalize.add_argument("--synthid", type=Path)
    finalize.add_argument(
        "--required-generator",
        action="append",
        default=[],
        metavar="NAME:COUNT",
    )
    finalize.add_argument(
        "--reselected-after-final",
        action="store_true",
        help="最終評価後に候補やしきい値を選び直した場合に指定します。"
        "この最終評価は採用根拠にせず、新しい未使用データを要求します。",
    )
    finalize.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "select":
            ledger = read_ledger(args.tuning_ledger, verify_files=False)
            candidates = _parse_candidates(args.candidate)
            selection = run_selection(
                ledger,
                {name: read_jsonl(path) for name, path in candidates.items()},
            )
            _write(args.output, selection)
            return 0 if selection["status"] == "selected" else 1
        selection = json.loads(args.selection.read_text(encoding="utf-8"))
        if not isinstance(selection, dict):
            raise ValueError("selection must be a JSON object")  # noqa: TRY004 -- invalid selection file
        report = run_final(
            selection,
            read_ledger(args.ledger, verify_files=False),
            measurements=read_jsonl(args.measurements) if args.measurements else None,
            decisions=read_jsonl(args.decisions) if args.decisions else None,
            comparisons=read_jsonl(args.comparison) if args.comparison else None,
            derived_conditions=read_jsonl(args.derived_conditions)
            if args.derived_conditions
            else None,
            synthid=read_jsonl(args.synthid) if args.synthid else None,
            required_generators=_parse_required_generators(args.required_generator),
            reselected_after_final=args.reselected_after_final,
        )
        _write(args.output, report)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"候補選択に失敗しました: {error}", file=sys.stderr)
        return 2
    return {"achieved": 0, "insufficient_evidence": 0, "not_met": 1}.get(
        report["status"], 1 if report["status"] == "no_candidate" else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
