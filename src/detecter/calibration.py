"""Select a reproducible evaluation-only threshold from tuning groups."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from bisect import bisect_left
from collections import defaultdict
from pathlib import Path
from typing import Any

from .evaluation import CONDITION_FIELDS, condition, read_jsonl
from .ledger import read_ledger

TARGETS = {
    "max_false_positive_rate": 0.001,
    "min_generated_detection_rate": 0.9,
    "unit": "source_group",
}


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and -sys.float_info.max <= value <= sys.float_info.max
    )


def config_id_for(config: dict[str, Any]) -> str:
    """Content identifier; omit the identifier itself when hashing JSON."""
    return _digest({key: value for key, value in config.items() if key != "config_id"})


def calibrate_records(
    ledger: list[dict[str, Any]],
    measurements: list[dict[str, Any]],
    *,
    split: str = "tuning",
) -> dict[str, Any]:
    if split != "tuning":
        raise ValueError("calibration requires split=tuning")
    if not ledger:
        raise ValueError("empty tuning ledger")
    # Reject every non-tuning row before selecting or joining any measurements.
    if any(row.get("split") != "tuning" for row in ledger):
        raise ValueError("non-tuning image or source group in calibration input")
    for records in (ledger, measurements):
        seen = set()
        for row in records:
            image_id = row.get("image_id")
            if (
                not isinstance(image_id, str)
                or not image_id.strip()
                or image_id in seen
            ):
                raise ValueError("missing or duplicate image_id")
            seen.add(image_id)
            if (
                not isinstance(row.get("sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is None
            ):
                raise ValueError(f"invalid sha256: {image_id}")
    measured = {row["image_id"]: row for row in measurements}
    if set(measured) != {row["image_id"] for row in ledger}:
        raise ValueError("missing measurements or image IDs outside tuning ledger")
    if len({row["sha256"] for row in ledger}) != len(ledger):
        raise ValueError("duplicate image hash in tuning ledger")
    model_condition = condition(measurements[0])
    if not all(isinstance(value, str) and value for value in model_condition):
        raise ValueError("missing model, weights or preprocessing version")
    groups: dict[str, list[tuple[str, float]]] = defaultdict(list)
    images = []
    calibration_data = []
    scores = set()
    for row in sorted(ledger, key=lambda item: item["image_id"]):
        image_id = row["image_id"]
        measurement = measured[image_id]
        if measurement.get("split", "tuning") != "tuning" or (
            "source_group" in measurement
            and measurement["source_group"] != row.get("source_group")
        ):
            raise ValueError(
                f"non-tuning image or source group in measurement: {image_id}"
            )
        if measurement["sha256"] != row["sha256"]:
            raise ValueError(f"image hash mismatch: {image_id}")
        if condition(measurement) != model_condition:
            raise ValueError(
                f"model, weights or preprocessing condition mismatch: {image_id}"
            )
        if measurement.get("status") != "ok" or not _finite_number(
            measurement.get("raw_score")
        ):
            raise ValueError(f"missing or failed measurement: {image_id}")
        if not isinstance(measurement.get("preprocessing"), dict):
            raise ValueError(f"missing preprocessing conditions: {image_id}")  # noqa: TRY004 - invalid JSON record
        if (
            not isinstance(row.get("source_group"), str)
            or not row["source_group"].strip()
        ):
            raise ValueError(f"missing source_group: {image_id}")
        if not isinstance(row.get("label"), str) or row["label"] not in {
            "real",
            "generated",
            "edited",
            "unknown",
        }:
            raise ValueError(f"invalid label: {image_id}")
        score = float(measurement["raw_score"])
        groups[row["source_group"]].append((row["label"], score))
        identity = {key: row[key] for key in ("image_id", "sha256", "source_group")}
        images.append(identity)
        calibration_data.append(
            {
                **identity,
                "label": row["label"],
                "raw_score": score,
                "preprocessing": measurement["preprocessing"],
            }
        )
        scores.add(score)
    grouped_scores: dict[str, list[float]] = defaultdict(list)
    for group, members in groups.items():
        labels = {label for label, _ in members}
        if len(labels) != 1:
            raise ValueError(f"conflicting labels in source_group: {group}")
        label = members[0][0]
        values = [score for _, score in members]
        grouped_scores[label].append(max(values) if label == "real" else min(values))
    real = sorted(grouped_scores["real"])
    generated = sorted(grouped_scores["generated"])
    if not real or not generated:
        raise ValueError("tuning requires real and generated source groups")
    upper = math.nextafter(max(scores), math.inf)
    if math.isfinite(upper):
        scores.add(upper)
    candidates: list[dict[str, Any]] = []
    for threshold in sorted(scores):
        false_positives = len(real) - bisect_left(real, threshold)
        detected = len(generated) - bisect_left(generated, threshold)
        metrics = {
            "false_positive_rate": {
                "numerator": false_positives,
                "denominator": len(real),
                "rate": false_positives / len(real),
            },
            "generated_detection_rate": {
                "numerator": detected,
                "denominator": len(generated),
                "rate": detected / len(generated),
            },
        }
        candidates.append(
            {
                "threshold": threshold,
                "meets_targets": false_positives * 1000 <= len(real)
                and detected * 10 >= len(generated) * 9,
                "metrics": metrics,
            }
        )
    # Stay within the false-positive limit, then maximize generated detection.
    eligible = [row for row in candidates if row["meets_targets"]]
    if not eligible:
        eligible = [
            row
            for row in candidates
            if row["metrics"]["false_positive_rate"]["numerator"] * 1000 <= len(real)
        ] or candidates
    selected = min(
        eligible,
        key=lambda row: (
            -row["metrics"]["generated_detection_rate"]["numerator"],
            row["metrics"]["false_positive_rate"]["numerator"],
            -row["threshold"],
        ),
    )
    config = {
        "schema_version": 1,
        "calibration_id": _digest(
            {"images": calibration_data, "condition": model_condition, "split": split}
        ),
        "calibration_images": images,
        **dict(zip(CONDITION_FIELDS, model_condition, strict=True)),
        "split": split,
        "threshold": selected["threshold"],
        "comparison": ">=",
        "targets": dict(TARGETS),
        "status": "candidate" if selected["meets_targets"] else "unmet",
        "usage": "evaluation",
        "required_provenance": [],
        "candidates": candidates,
        "selected_metrics": selected["metrics"],
        "source_group_counts": {
            label: len(values) for label, values in sorted(grouped_scores.items())
        },
        "excluded_labels": ["edited", "unknown"],
        "group_policy": "any_positive_real; all_positive_generated",
        "selection_policy": "meet_fpr_limit; highest_detection; lowest_fpr; highest_threshold",
    }
    return {"config_id": config_id_for(config), **config}


def validate_config(
    config: dict[str, Any],
    measurement: dict[str, Any] | None = None,
    *,
    usage: str = "evaluation",
) -> None:
    """Reject incompatible or unapproved settings before applying their threshold."""
    if usage not in {"evaluation", "production"}:
        raise ValueError("usage must be evaluation or production")
    if config.get("status") not in {"candidate", "validated"}:
        raise ValueError("unmet or invalid calibration config")
    if config.get("usage") not in {"evaluation", "production"}:
        raise ValueError("invalid config usage")
    if usage == "production" and (
        config["status"] != "validated" or config["usage"] != "production"
    ):
        raise ValueError("production requires validated production config")
    if config.get("comparison") != ">=" or not _finite_number(config.get("threshold")):
        raise ValueError("invalid threshold or comparison")
    if not isinstance(config.get("config_id"), str) or not config["config_id"]:
        raise ValueError("missing config_id")
    calibration_id = config.get("calibration_id")
    if (
        not isinstance(calibration_id, str)
        or re.fullmatch(r"[0-9a-f]{64}", calibration_id) is None
    ):
        raise ValueError("invalid calibration_id")
    images = config.get("calibration_images")
    if not isinstance(images, list) or not images:
        raise ValueError("missing calibration_images")
    seen_ids, seen_hashes = set(), set()
    for image in images:
        if not isinstance(image, dict) or any(
            not isinstance(image.get(key), str) or not image[key].strip()
            for key in ("image_id", "sha256", "source_group")
        ):
            raise ValueError("invalid calibration image identity")
        if (
            re.fullmatch(r"[0-9a-f]{64}", image["sha256"]) is None
            or image["image_id"] in seen_ids
            or image["sha256"] in seen_hashes
        ):
            raise ValueError("invalid or duplicate calibration image")
        seen_ids.add(image["image_id"])
        seen_hashes.add(image["sha256"])
    if config.get("targets") != TARGETS:
        raise ValueError("invalid calibration targets")
    required = config.get("required_provenance")
    if (
        not isinstance(required, list)
        or any(not isinstance(value, str) or not value.strip() for value in required)
        or len(set(required)) != len(required)
    ):
        raise ValueError("invalid required_provenance")
    if config["config_id"] != config_id_for(config):
        raise ValueError("config_id does not match config contents")
    if not all(isinstance(value, str) and value for value in condition(config)):
        raise ValueError("missing model, weights or preprocessing version")
    if measurement is not None:
        if condition(measurement) != condition(config):
            raise ValueError("model, weights or preprocessing condition mismatch")
        if measurement.get("status") != "ok" or not _finite_number(
            measurement.get("raw_score")
        ):
            raise ValueError("missing or failed measurement")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="調整用の元画像グループから評価用の判定境界を選びます"
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--measurements", type=Path, required=True)
    parser.add_argument("--split", default="tuning")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        config = calibrate_records(
            read_ledger(args.ledger, verify_files=False),
            read_jsonl(args.measurements),
            split=args.split,
        )
        text = (
            json.dumps(config, ensure_ascii=False, sort_keys=True, allow_nan=False)
            + "\n"
        )
        if str(args.output) == "-":
            print(text, end="")
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(text)
    except (ValueError, OSError) as error:
        print(f"判定境界を選択できません: {error}", file=sys.stderr)
        return 2
    return 0 if config["status"] == "candidate" else 1


if __name__ == "__main__":
    raise SystemExit(main())
