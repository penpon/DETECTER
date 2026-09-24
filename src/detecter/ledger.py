"""Validate evaluation ledgers and split original-image groups reproducibly."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections.abc import Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from .core import file_sha256

LABELS = {"real", "generated", "edited", "unknown"}
SPLITS = {"unassigned", "tuning", "evaluation"}


def _validate_row(row: Any) -> None:
    if not isinstance(row, dict):
        raise ValueError("台帳の各行はオブジェクトにしてください")  # noqa: TRY004 -- invalid JSON data
    for field in (
        "image_id",
        "path",
        "source_group",
        "sha256",
        "source",
        "license",
        "label",
        "split",
    ):
        if not isinstance(row.get(field), str) or not row[field].strip():
            raise ValueError(f"{field} は空でない文字列が必要です")
    if re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is None:
        raise ValueError("sha256 は小文字の16進数64文字が必要です")
    if row["label"] not in LABELS or row["split"] not in SPLITS:
        raise ValueError("label または split が契約と一致しません")
    history = row.get("history")
    if not isinstance(history, list) or any(
        not isinstance(item, dict) for item in history
    ):
        raise ValueError("history は加工条件オブジェクトの配列が必要です")
    for field in ("generator", "camera", "image_kind"):
        if field in row and not isinstance(row[field], str):
            raise ValueError(f"{field} は文字列が必要です")
    if "source_image_id" in row or "source_sha256" in row:
        source_id = row.get("source_image_id")
        source_hash = row.get("source_sha256")
        if (
            not isinstance(source_id, str)
            or not source_id.strip()
            or source_id == row["image_id"]
        ):
            raise ValueError("派生画像には別の元画像IDが必要です")
        if (
            not isinstance(source_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", source_hash) is None
        ):
            raise ValueError("派生画像には元画像のSHA-256が必要です")
        if not history:
            raise ValueError("派生画像には加工履歴が必要です")


def _validate_relations(rows: list[dict[str, Any]]) -> None:
    by_id: dict[str, dict[str, Any]] = {}
    hashes: set[str] = set()
    groups: dict[str, tuple[str, str]] = {}
    references: dict[str, tuple[str, str, str, str]] = {}
    for row in rows:
        _validate_row(row)
        if row["image_id"] in by_id or row["sha256"] in hashes:
            raise ValueError(f"画像IDまたはハッシュが重複しています: {row['image_id']}")
        by_id[row["image_id"]] = row
        hashes.add(row["sha256"])
        group_state = (row["label"], row["split"])
        if groups.setdefault(row["source_group"], group_state) != group_state:
            raise ValueError(
                f"元画像グループのラベルまたは分割先が矛盾しています: {row['source_group']}"
            )
        if "source_image_id" in row:
            reference = (
                row["source_sha256"],
                row["source_group"],
                row["label"],
                row["split"],
            )
            if references.setdefault(row["source_image_id"], reference) != reference:
                raise ValueError(
                    f"元画像の参照情報が矛盾しています: {row['source_image_id']}"
                )
    for row in rows:
        parent = by_id.get(row.get("source_image_id", ""))
        if parent is None:
            continue
        if row["source_sha256"] != parent["sha256"] or any(
            row[field] != parent[field] for field in ("source_group", "label", "split")
        ):
            raise ValueError(
                f"派生画像と元画像の識別情報が一致しません: {row['image_id']}"
            )
        parent_history = parent["history"]
        if (
            len(row["history"]) <= len(parent_history)
            or row["history"][: len(parent_history)] != parent_history
        ):
            raise ValueError(
                f"派生画像の加工履歴が継承されていません: {row['image_id']}"
            )


def read_ledger(path: Path | str, *, verify_files: bool = True) -> list[dict[str, Any]]:
    """Read JSONL rows, resolving image paths relative to the ledger file."""
    ledger = Path(path).expanduser().resolve()
    rows = [
        json.loads(line)
        for line in ledger.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    _validate_relations(rows)
    for row in rows:
        row["path"] = str((ledger.parent / row["path"]).resolve())
        if verify_files:
            try:
                actual_hash = file_sha256(Path(row["path"]))
            except OSError as error:
                raise ValueError(
                    f"画像を読み込めません: {row['image_id']}: {error}"
                ) from error
            if row["sha256"] != actual_hash:
                raise ValueError(f"画像ハッシュが一致しません: {row['image_id']}")
    return rows


def split_ledger(
    rows: list[dict[str, Any]],
    *,
    seed: int,
    evaluation_fraction: float = 0.2,
    holdout_generators: Sequence[str] = (),
    holdout_cameras: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Return new rows split by source group, with named holdouts in evaluation."""
    _validate_relations(rows)
    if not 0 <= evaluation_fraction <= 1:
        raise ValueError("evaluation_fraction は0以上1以下にしてください")
    for field, requested in (
        ("generator", holdout_generators),
        ("camera", holdout_cameras),
    ):
        unknown = set(requested) - {row.get(field) for row in rows}
        if unknown:
            raise ValueError(
                f"台帳にない {field} が指定されています: {sorted(unknown)}"
            )
    groups = {row["source_group"] for row in rows}
    ranked = sorted(
        groups,
        key=lambda group: (
            hashlib.sha256(f"{seed}\0{group}".encode()).hexdigest(),
            group,
        ),
    )
    evaluation = set(ranked[: math.ceil(len(groups) * evaluation_fraction)])
    evaluation.update(
        row["source_group"]
        for row in rows
        if row.get("generator") in holdout_generators
        or row.get("camera") in holdout_cameras
    )
    result = deepcopy(rows)
    for row in result:
        row["split"] = "evaluation" if row["source_group"] in evaluation else "tuning"
    return sorted(result, key=lambda row: row["image_id"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="評価画像の台帳を検証・分割します")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("ledger", type=Path)
    split = commands.add_parser("split")
    split.add_argument("ledger", type=Path)
    split.add_argument("--seed", type=int, required=True)
    split.add_argument("--evaluation-fraction", type=float, default=0.2)
    split.add_argument("--holdout-generator", action="append", default=[])
    split.add_argument("--holdout-camera", action="append", default=[])
    split.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        rows = read_ledger(args.ledger)
        if args.command == "validate":
            print(
                json.dumps(
                    {
                        "status": "ok",
                        "images": len(rows),
                        "source_groups": len({row["source_group"] for row in rows}),
                    }
                )
            )
        else:
            result = split_ledger(
                rows,
                seed=args.seed,
                evaluation_fraction=args.evaluation_fraction,
                holdout_generators=args.holdout_generator,
                holdout_cameras=args.holdout_camera,
            )
            text = "".join(
                json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                for row in result
            )
            if str(args.output) == "-":
                print(text, end="")
            else:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                with args.output.open("x", encoding="utf-8") as stream:
                    stream.write(text)
    except (ValueError, OSError) as error:
        print(f"台帳処理に失敗しました: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
