"""Measure identical file identities independently; never combine model scores."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import community_forensics as cf
from . import cure as cure_mod
from .core import UfdDetector, default_cache_dir
from .ufd_batch import load_inputs, measure

COMPARISON_MODELS = ("community-forensics", "ufd", "cure")
DEFAULT_MODELS = ("community-forensics", "ufd")


def compare_records(
    inputs: list[dict[str, Any]],
    *,
    ufd_detector: Any = None,
    community_model: Any = None,
    cure_model: Any = None,
    cache_dir: Path | None = None,
    device: str = "cpu",
    models: list[str] | tuple[str, ...] | None = None,
    cure_device: str = "cpu",
    adapter_checkpoint: Path | None = None,
    base_checkpoint: Path | None = None,
) -> list[dict[str, Any]]:
    selected = tuple(models) if models is not None else DEFAULT_MODELS
    if len(set(selected)) != len(selected) or any(
        name not in COMPARISON_MODELS for name in selected
    ):
        raise ValueError("models must list community-forensics, ufd and cure once")
    ids = [row["image_id"] for row in inputs]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate image_id")
    ufd_error = community_error = cure_error = None
    if inputs:
        if "ufd" in selected and ufd_detector is None:
            try:
                ufd_detector = UfdDetector(cache_dir=cache_dir, device=device)
            except Exception as error:  # noqa: BLE001 - preserve the other model
                ufd_error = error
        if "community-forensics" in selected and community_model is None:
            try:
                community_model = cf.load_model(cache_dir)
            except Exception as error:  # noqa: BLE001
                community_error = error
        if "cure" in selected and cure_model is None:
            try:
                cure_model = cure_mod.load_model(
                    cache_dir,
                    adapter_checkpoint=adapter_checkpoint,
                    base_checkpoint=base_checkpoint,
                    device=cure_device,
                )
            except Exception as error:  # noqa: BLE001
                cure_error = error
    records = []
    for row in sorted(inputs, key=lambda r: r["image_id"]):
        path = Path(row["path"])
        identity = {"image_id": row["image_id"], "expected_sha256": row["sha256"]}
        pair = []
        if "community-forensics" in selected:
            pair.append(
                cf.measure(
                    path,
                    **identity,
                    cache_dir=cache_dir,
                    device="cpu",
                    model=community_model,
                    model_error=community_error,
                )
            )
        if "ufd" in selected:
            pair.append(
                measure(
                    path,
                    **identity,
                    detector=ufd_detector,
                    device=device,
                    model_error=ufd_error,
                )
            )
        if "cure" in selected:
            pair.append(
                cure_mod.measure(
                    path,
                    **identity,
                    cache_dir=cache_dir,
                    device=cure_device,
                    model=cure_model,
                    model_error=cure_error,
                    adapter_checkpoint=adapter_checkpoint,
                    base_checkpoint=base_checkpoint,
                )
            )
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
        description="同じ画像をCommunity ForensicsとUFD、任意でCuReで個別計測します"
    )
    parser.add_argument("models", nargs="+", choices=COMPARISON_MODELS)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, default=default_cache_dir())
    parser.add_argument(
        "--device",
        choices=("cpu", "auto", "cuda"),
        default="cpu",
        help="UFDの実行機器。Community ForensicsはCPUです",
    )
    parser.add_argument(
        "--cure-device",
        choices=("cpu", "auto", "cuda"),
        default="cpu",
        help="CuReの実行機器",
    )
    parser.add_argument("--adapter-checkpoint", type=Path, default=None)
    parser.add_argument("--base-checkpoint", type=Path, default=None)
    args = parser.parse_args(argv)
    if set(args.models) not in (
        {"community-forensics", "ufd"},
        {"community-forensics", "ufd", "cure"},
    ):
        parser.error(
            "community-forensicsとufdを指定し、"
            "CuReを含める場合は3件とも指定してください"
        )
    try:
        records = compare_records(
            load_inputs(args.ledger),
            cache_dir=args.cache_dir,
            device=args.device,
            models=list(args.models),
            cure_device=args.cure_device,
            adapter_checkpoint=args.adapter_checkpoint,
            base_checkpoint=args.base_checkpoint,
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
