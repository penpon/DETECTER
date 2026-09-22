"""Evaluate saved records; inference never receives ground-truth labels."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

CONDITION_FIELDS = (
    "model",
    "model_version",
    "weights_version",
    "preprocessing_version",
)
POSITIVE_STATES = {"ai_likely", "ai_evidence_confirmed"}
DECISION_STATES = POSITIVE_STATES | {"no_ai_signal_detected", "inconclusive"}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: expected object")  # noqa: TRY004
            records.append(row)
    return records


def condition(record: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(record.get(key) for key in CONDITION_FIELDS)


def _index(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {}
    for row in records:
        image_id = row.get("image_id")
        if not isinstance(image_id, str) or not image_id:
            raise ValueError("missing image_id")
        if image_id in result:
            raise ValueError(
                f"duplicate image_id: {image_id}; select one model and run"
            )
        result[image_id] = row
    return result


def _metric(
    rows: list[dict[str, Any]], predicate: Any, *, exclude_unresolved: bool = False
) -> dict[str, Any]:
    eligible = [row for row in rows if not exclude_unresolved or row["resolved"]]
    excluded = [row for row in rows if exclude_unresolved and not row["resolved"]]
    numerator = sum(bool(predicate(row)) for row in eligible)
    denominator = len(eligible)
    observed = any(row["attempted"] for row in eligible)
    status = (
        "insufficient_data"
        if not rows
        else "not_measured"
        if not observed or not denominator
        else "measured"
    )
    return {
        "target_count": len(rows),
        "numerator": numerator,
        "denominator": denominator,
        "rate": numerator / denominator if status == "measured" else None,
        "status": status,
        "excluded_count": len(excluded),
        "excluded_reasons": dict(
            Counter(reason for row in excluded for reason in row["reasons"])
        ),
    }


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result = {
        "false_positive_rate": _metric(
            [r for r in rows if r["label"] == "real"],
            lambda r: r["positive"],
            exclude_unresolved=True,
        ),
        "generated_detection_rate": _metric(
            [r for r in rows if r["label"] == "generated"], lambda r: r["positive"]
        ),
        "edited_detection_rate": _metric(
            [r for r in rows if r["label"] == "edited"], lambda r: r["positive"]
        ),
        "hold_rate": _metric(rows, lambda r: r["held"]),
        "failure_rate": _metric(rows, lambda r: r["failed"]),
    }
    return result


def _units(rows: list[dict[str, Any]], unit: str) -> list[dict[str, Any]]:
    if unit == "image":
        return rows
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["source_group"]].append(row)
    result = []
    for group, members in sorted(grouped.items()):
        labels = {row["label"] for row in members}
        splits = {row["split"] for row in members}
        if len(labels) != 1 or len(splits) != 1:
            raise ValueError(f"conflicting label or split in source_group: {group}")
        real = members[0]["label"] == "real"
        positive = (
            any(row["positive"] for row in members)
            if real
            else all(row["positive"] for row in members)
        )
        result.append(
            {
                "source_group": group,
                "image_ids": [row["image_id"] for row in members],
                "label": members[0]["label"],
                "split": members[0]["split"],
                "positive": positive,
                "resolved": positive or all(row["resolved"] for row in members),
                "held": any(row["held"] for row in members),
                "failed": any(row["failed"] for row in members),
                "attempted": any(row["attempted"] for row in members),
                "reasons": sorted(
                    {reason for row in members for reason in row["reasons"]}
                ),
            }
        )
    return result


def evaluate_records(
    ledger: list[dict[str, Any]],
    measurements: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    *,
    unit: str = "image",
    split: str | None = None,
) -> dict[str, Any]:
    if unit not in {"image", "source_group"}:
        raise ValueError("unit must be image or source_group")
    _index(ledger)
    group_states: dict[str, tuple[Any, Any]] = {}
    for row in ledger:
        group = row.get("source_group")
        if not isinstance(group, str) or not group:
            raise ValueError("missing source_group")
        state = (row.get("label"), row.get("split"))
        if group_states.setdefault(group, state) != state:
            raise ValueError(f"conflicting label or split in source_group: {group}")
    measured, decided = _index(measurements), _index(decisions)
    rows = [r for r in ledger if split is None or r.get("split") == split]
    ids = {r["image_id"] for r in rows}
    conditions = {condition(r) for r in measurements if r["image_id"] in ids}
    if (
        any(not all(isinstance(v, str) and v for v in c) for c in conditions)
        or len(conditions) > 1
    ):
        raise ValueError("mixed or missing measurement conditions")
    configs = {r.get("config_id") for r in decisions if r["image_id"] in ids}
    if len(configs) > 1:
        raise ValueError("mixed decision configs")
    targets: list[dict[str, Any]] = []
    for row in rows:
        if row.get("label") not in {"real", "generated", "edited", "unknown"}:
            raise ValueError("unknown ledger label")
        if not row.get("source_group") or not row.get("sha256") or not row.get("split"):
            raise ValueError("missing ledger identity")
        measurement, decision = (
            measured.get(row["image_id"]),
            decided.get(row["image_id"]),
        )
        reasons = []
        attempted = bool(measurement and measurement.get("sha256") == row["sha256"])
        failed = bool(
            attempted and measurement and measurement.get("status") == "error"
        )
        if measurement is None:
            reasons.append("measurement_missing")
        elif measurement.get("sha256") != row["sha256"]:
            reasons.append("measurement_hash_mismatch")
        elif measurement.get("status") != "ok":
            reasons.append(
                "measurement_failed" if failed else "measurement_status_invalid"
            )
        elif (
            isinstance(measurement.get("raw_score"), bool)
            or not isinstance(measurement.get("raw_score"), (int, float))
            or not math.isfinite(measurement["raw_score"])
        ):
            reasons.append("score_invalid")
        if decision is None:
            reasons.append("decision_missing")
        elif decision.get("sha256") != row["sha256"]:
            reasons.append("decision_hash_mismatch")
        elif not decision.get("config_id"):
            reasons.append("config_missing")
        elif measurement and condition(decision) != condition(measurement):
            reasons.append("condition_mismatch")
        elif decision.get("state") not in DECISION_STATES:
            reasons.append("decision_state_invalid")
        state = decision.get("state") if decision and not reasons else "inconclusive"
        if state == "inconclusive" and decision:
            reasons.extend(decision.get("reasons") or ["decision_inconclusive"])
        targets.append(
            {
                **{
                    k: row.get(k)
                    for k in (
                        "image_id",
                        "sha256",
                        "source_group",
                        "label",
                        "split",
                        "generator",
                        "camera",
                    )
                },
                "history": row.get("history", []),
                "config_id": decision.get("config_id") if decision else None,
                "state": state,
                "positive": state in POSITIVE_STATES,
                "resolved": state in POSITIVE_STATES | {"no_ai_signal_detected"},
                "held": state == "inconclusive",
                "failed": failed,
                "attempted": attempted,
                "reasons": sorted(set(reasons)),
            }
        )
    # Validate group boundaries even for image-level output.
    grouped = _units(targets, "source_group")
    selected = targets if unit == "image" else grouped
    breakdowns = {}
    for field in ("history", "generator", "camera"):
        partitions: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for target in targets:
            value = target.get(field)
            key = (
                json.dumps(value, ensure_ascii=False, sort_keys=True)
                if field == "history"
                else str(value or "unknown")
            )
            partitions[key].append(target)
        breakdowns[field] = {
            key: _metrics(_units(items, unit))
            for key, items in sorted(partitions.items())
        }
    states: dict[str, set[str]] = defaultdict(set)
    for target in targets:
        if target["resolved"]:
            states[target["source_group"]].add(
                "positive" if target["positive"] else "negative"
            )
    reversals = sorted(group for group, values in states.items() if len(values) > 1)
    return {
        "schema_version": 1,
        "unit": unit,
        "split": split,
        "target_count": len(selected),
        "image_count": len(targets),
        "source_group_count": len(grouped),
        "conditions": dict(zip(CONDITION_FIELDS, next(iter(conditions))))
        if conditions
        else None,
        "config_id": next(iter(configs)) if configs else None,
        "metrics": _metrics(selected),
        "breakdowns": breakdowns,
        "targets": targets,
        "reversals": {
            "count": len(reversals),
            "denominator": len(grouped),
            "source_groups": reversals,
        },
        "group_policy": "any_positive_real; all_positive_generated_or_edited",
        "unknown_label_count": sum(r["label"] == "unknown" for r in selected),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="保存済み計測と判定を分母付きで集計します"
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--measurements", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--unit", choices=("image", "source_group"), default="image")
    parser.add_argument("--split")
    parser.add_argument("--output", type=Path, default=Path("-"))
    args = parser.parse_args(argv)
    try:
        report = evaluate_records(
            read_jsonl(args.ledger),
            read_jsonl(args.measurements),
            read_jsonl(args.decisions),
            unit=args.unit,
            split=args.split,
        )
        text = (
            json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False)
            + "\n"
        )
        if str(args.output) == "-":
            print(text, end="")
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding="utf-8")
    except (ValueError, OSError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
