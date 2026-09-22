"""Measure identical file identities independently; never combine model scores."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import community_forensics as cf
from .core import UfdDetector, default_cache_dir
from .ufd_batch import load_inputs, measure


def compare_records(
    inputs: list[dict[str, Any]],
    *,
    ufd_detector: Any = None,
    community_model: Any = None,
    cache_dir: Path | None = None,
    device: str = "cpu",
) -> list[dict[str, Any]]:
    ids = [row["image_id"] for row in inputs]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate image_id")
    ufd_error = community_error = None
    if inputs:
        if ufd_detector is None:
            try:
                ufd_detector = UfdDetector(cache_dir=cache_dir, device=device)
            except Exception as error:  # noqa: BLE001 - preserve the other model
                ufd_error = error
        if community_model is None:
            try:
                community_model = cf.load_model(cache_dir)
            except Exception as error:  # noqa: BLE001
                community_error = error
    records = []
    for row in sorted(inputs, key=lambda r: r["image_id"]):
        path = Path(row["path"])
        identity = {"image_id": row["image_id"], "expected_sha256": row["sha256"]}
        pair = [
            cf.measure(
                path,
                **identity,
                cache_dir=cache_dir,
                device="cpu",
                model=community_model,
                model_error=community_error,
            ),
            measure(
                path,
                **identity,
                detector=ufd_detector,
                device=device,
                model_error=ufd_error,
            ),
        ]
        for record in pair:
            record.update(
                source_image_id=row.get("source_image_id", row["image_id"]),
                source_sha256=row.get("source_sha256", row["sha256"]),
                history=row.get("history", []),
            )
            records.append(record)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="同じ画像をCommunity ForensicsとUFDで個別計測します"
    )
    parser.add_argument("models", nargs=2, choices=("community-forensics", "ufd"))
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, default=default_cache_dir())
    parser.add_argument(
        "--device",
        choices=("cpu", "auto", "cuda"),
        default="cpu",
        help="UFDの実行機器。Community ForensicsはCPUです",
    )
    args = parser.parse_args(argv)
    if set(args.models) != {"community-forensics", "ufd"}:
        parser.error("community-forensicsとufdを1回ずつ指定してください")
    try:
        records = compare_records(
            load_inputs(args.ledger), cache_dir=args.cache_dir, device=args.device
        )
        if str(args.output) != "-":
            args.output.parent.mkdir(parents=True, exist_ok=True)
        stream = (
            sys.stdout
            if str(args.output) == "-"
            else args.output.open("x", encoding="utf-8")
        )
        try:
            for record in records:
                stream.write(
                    json.dumps(
                        record, ensure_ascii=False, sort_keys=True, allow_nan=False
                    )
                    + "\n"
                )
        finally:
            if stream is not sys.stdout:
                stream.close()
    except (ValueError, OSError) as error:
        parser.error(str(error))
    return 1 if any(r["status"] == "error" for r in records) else 0


if __name__ == "__main__":
    raise SystemExit(main())
