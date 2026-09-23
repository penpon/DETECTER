"""Independent, label-free UFD measurements with per-image failure records."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import platform
import re
import sys
from pathlib import Path
from typing import Any

from .core import (
    UFD_COMMIT,
    UFD_HEAD_SHA256,
    UFD_PREPROCESSING_VERSION,
    UfdDetector,
    analyze_full_area_tiles,
    default_cache_dir,
    inspect_image,
)

CLIP_SHA256 = "b8cca3fd41ae0c99ba7e8951adf17d267cdb84cd88be6f7c2e0eca1737a03836"
WEIGHTS_VERSION = f"{UFD_HEAD_SHA256}:{CLIP_SHA256}"
PREPROCESSING_VERSION = UFD_PREPROCESSING_VERSION
TILE_PREPROCESSING_VERSION = "ufd-rgb-exif-grid8-lanczos224-mean-v2"


def model_condition(mode: str = "single") -> dict[str, str]:
    if mode not in {"single", "tiles"}:
        raise ValueError("mode must be single or tiles")
    return {
        "model": "ufd",
        "model_version": UFD_COMMIT,
        "weights_version": WEIGHTS_VERSION,
        "preprocessing_version": PREPROCESSING_VERSION
        if mode == "single"
        else TILE_PREPROCESSING_VERSION,
    }


def measure(
    path: Path,
    *,
    image_id: str,
    expected_sha256: str | None = None,
    detector: Any = None,
    cache_dir: Path | None = None,
    device: str = "cpu",
    mode: str = "single",
    model_error: Exception | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema_version": 1,
        "image_id": image_id,
        "sha256": expected_sha256,
        **model_condition(mode),
        "status": "error",
        "raw_score": None,
        "error": None,
        "preprocessing": {
            "mode": mode,
            "rgb": True,
            "exif_transpose": True,
            "crop": "center224" if mode == "single" else None,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "device": str(getattr(detector, "device", device)),
            "torch": importlib.metadata.version("torch"),
            "torchvision": importlib.metadata.version("torchvision"),
            "pillow": importlib.metadata.version("Pillow"),
            "pillow_heif": importlib.metadata.version("pillow-heif"),
        },
    }
    try:
        if not image_id:
            raise ValueError("image_id is required")
        media = inspect_image(path)
        record["observed_sha256"] = media["sha256"]
        if expected_sha256 is not None and media["sha256"] != expected_sha256:
            raise ValueError("image hash mismatch")
        record["sha256"] = media["sha256"]
        if model_error is not None:
            raise model_error
        if detector is None:
            detector = UfdDetector(cache_dir=cache_dir, device=device)
        record["environment"]["device"] = str(getattr(detector, "device", device))
        if mode == "tiles":
            tiled = analyze_full_area_tiles(path, detector)
            if tiled["status"] != "ok":
                raise RuntimeError(tiled["error_type"])
            score = tiled["mean"]
            record["preprocessing"] = {
                **record["preprocessing"],
                "tile_count": tiled["tile_count"],
                "max_tiles": 64,
                "tile_size": 224,
                "interpolation": "LANCZOS",
                "aggregation": "mean",
            }
        else:
            score = detector.score(path)
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(score)
        ):
            raise ValueError("model returned non-finite score")
        record.update(status="ok", raw_score=float(score))
    except Exception as error:  # noqa: BLE001 - keep a failed image in the denominator
        record["error"] = f"{type(error).__name__}: {error}"
    return record


def load_inputs(path: Path) -> list[dict[str, Any]]:
    """Project identities before inference; never forward a ground-truth row."""
    result = []
    seen = set()
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("image_id"), str)
                or not row["image_id"]
            ):
                raise ValueError("ledger requires image_id")
            if row["image_id"] in seen:
                raise ValueError(f"duplicate image_id: {row['image_id']}")
            seen.add(row["image_id"])
            if not isinstance(row.get("sha256"), str) or not re.fullmatch(
                "[0-9a-f]{64}", row["sha256"]
            ):
                raise ValueError("ledger requires SHA-256")
            if not isinstance(row.get("path"), str) or not row["path"]:
                raise ValueError("ledger requires image path")
            image_path = Path(row["path"]).expanduser()
            result.append(
                {
                    "image_id": row["image_id"],
                    "sha256": row["sha256"],
                    "path": image_path
                    if image_path.is_absolute()
                    else path.parent / image_path,
                    "source_sha256": row.get("source_sha256", row["sha256"]),
                    "source_image_id": row.get("source_image_id", row["image_id"]),
                    "history": row.get("history", []),
                }
            )
    return result


def measure_batch(
    inputs: list[dict[str, Any]],
    *,
    detector: Any = None,
    cache_dir: Path | None = None,
    device: str = "cpu",
    mode: str = "single",
) -> list[dict[str, Any]]:
    model_condition(mode)
    setup_error = None
    if detector is None and inputs:
        try:
            detector = UfdDetector(cache_dir=cache_dir, device=device)
        except Exception as error:  # noqa: BLE001
            setup_error = error
    records = []
    for row in inputs:
        record = measure(
            Path(row["path"]),
            image_id=row["image_id"],
            expected_sha256=row["sha256"],
            detector=detector,
            device=device,
            mode=mode,
            model_error=setup_error,
        )
        record.update(
            source_sha256=row.get("source_sha256", row["sha256"]),
            history=row.get("history", []),
        )
        records.append(record)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="台帳の画像をUFDで個別に計測します")
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, default=default_cache_dir())
    parser.add_argument("--device", choices=("cpu", "auto", "cuda"), default="cpu")
    parser.add_argument("--mode", choices=("single", "tiles"), default="single")
    args = parser.parse_args(argv)
    try:
        records = measure_batch(
            load_inputs(args.ledger),
            cache_dir=args.cache_dir,
            device=args.device,
            mode=args.mode,
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
