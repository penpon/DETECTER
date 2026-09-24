"""Fully-automatic unified AI probability: image path in, one JSON object out.

Layers run without any human step:

1. Deterministic bypass (#41): verified C2PA / SynthID evidence settles the
   probability at 0.0 or 1.0 before any passive model runs.
2. Passive inference: raw scores from Community Forensics 384, CuRe and
   UniversalFakeDetect on CPU.
3. Statistical calibration (#40): logistic fusion of the raw scores into a
   base AI probability.
4. Jev final composition (#42): one System One call folds sanitized metadata
   and the base probability into ``final_ai_probability`` and ``confidence``.

Models and the Jev client are built lazily so a deterministic bypass never
loads a detector, and a missing Jev key degrades to the base probability
instead of failing the command.
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .base_probability import calibrated_ai_probability
from .core import (
    MAX_INPUT_BYTES,
    UfdDetector,
    default_cache_dir,
    deterministic_bypass,
    inspect_c2pa,
    inspect_exif_sanitized,
    inspect_image,
)
from .final_probability import JEV_MODEL, final_ai_probability

SCHEMA_VERSION = 1

_SMARTPHONE_KEYWORDS = (
    "iphone",
    "pixel",
    "galaxy",
    "xperia",
    "aquos",
    "huawei",
    "xiaomi",
    "oppo",
    "vivo",
    "oneplus",
    "redmi",
    "arrows",
    "rakuten",
)
_CAMERA_MAKERS = (
    "canon",
    "nikon",
    "sony",
    "fujifilm",
    "panasonic",
    "olympus",
    "om system",
    "leica",
    "ricoh",
    "pentax",
    "hasselblad",
    "sigma",
    "casio",
    "kodak",
)


def device_category(exif: dict[str, Any]) -> str:
    """Map sanitized camera EXIF to a coarse device class for the Jev state."""
    camera = exif.get("camera")
    if not isinstance(camera, dict):
        return "unknown"
    text = " ".join(
        str(camera.get(key, "")) for key in ("make", "model", "lens_model")
    ).lower()
    if not text.strip():
        return "unknown"
    if "scanner" in text or "scanjet" in text:
        return "scanner"
    if any(word in text for word in _SMARTPHONE_KEYWORDS):
        return "smartphone"
    if any(word in text for word in _CAMERA_MAKERS):
        return "camera"
    return "unknown"


def _percent(probability: float) -> str:
    return f"{probability * 100:.1f}%"


def _measure(
    module_name: str,
    path: Path,
    *,
    image_id: str,
    sha256: str,
    cache_dir: Path | None,
    device: str,
) -> dict[str, Any]:
    """Run one passive model's measure(); import or load failures stay local."""
    try:
        module = importlib.import_module(module_name)
        return module.measure(
            path,
            image_id=image_id,
            expected_sha256=sha256,
            cache_dir=cache_dir,
            device=device,
        )
    except Exception as error:  # noqa: BLE001 - one model must not sink the image
        return {
            "status": "error",
            "raw_score": None,
            "error": f"{type(error).__name__}: {error}",
        }


def _ufd_measure(
    path: Path,
    *,
    image_id: str,
    sha256: str,
    detector: Any,
    cache_dir: Path | None,
    device: str,
) -> dict[str, Any]:
    try:
        from .ufd_batch import measure

        return measure(
            path,
            image_id=image_id,
            expected_sha256=sha256,
            detector=detector,
            cache_dir=cache_dir,
            device=device,
        )
    except Exception as error:  # noqa: BLE001
        return {
            "status": "error",
            "raw_score": None,
            "error": f"{type(error).__name__}: {error}",
        }


def analyze_image(
    path: Path,
    *,
    device: str = "cpu",
    cache_dir: Path | None = None,
    c2pa_trust_anchors: Path | None = None,
    max_bytes: int = MAX_INPUT_BYTES,
    jev_client: Any = None,
    detectors: dict[str, Any] | None = None,
    synthid_records: Any = None,
) -> dict[str, Any]:
    """Run the whole pipeline for one image and return the unified record."""
    started = time.perf_counter()
    resolved = Path(path).expanduser().resolve()
    image_id = str(resolved)
    media = inspect_image(resolved, max_bytes=max_bytes)
    c2pa = inspect_c2pa(resolved, trust_anchors=c2pa_trust_anchors)
    exif = inspect_exif_sanitized(resolved)
    sha256 = media["sha256"]

    if synthid_records is None:
        synthid: dict[str, Any] = {
            "status": "not_checked",
            "state": "not_checked",
            "automatically_verified": False,
            "reason": "automatic_synthid_verification_unavailable",
        }
    else:
        from .synthid_manual import summarize_synthid

        synthid = summarize_synthid(
            image_id=image_id, sha256=sha256, records=synthid_records
        )
    bypass = deterministic_bypass(c2pa, synthid)
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "analyzed_at": datetime.now(UTC).isoformat(),
        "image_id": image_id,
        "sha256": sha256,
        "pipeline": [
            "deterministic_bypass",
            "passive_inference",
            "statistical_calibration",
            "jev_composition",
        ],
        "media": media,
        "c2pa": c2pa,
        "synthid": synthid,
        "exif": exif,
    }
    if bypass is not None:
        probability = float(bypass["ai_probability"])
        record.update(
            ai_probability=probability,
            ai_probability_percent=_percent(probability),
            confidence=1.0,
            state=bypass["state"],
            bypass=bypass,
            breakdown={
                "c2pa": c2pa,
                "synthid": synthid,
                "camera": exif.get("camera", {}),
            },
        )
        record["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
        return record

    detectors = detectors if detectors is not None else {}
    if "ufd" not in detectors:
        try:
            detectors["ufd"] = UfdDetector(cache_dir=cache_dir, device=device)
        except Exception as error:  # noqa: BLE001 - kept as a model record below
            detectors["ufd"] = None
            detectors["ufd_error"] = error
    models = {
        "community_forensics_384": _measure(
            "detecter.community_forensics",
            resolved,
            image_id=image_id,
            sha256=sha256,
            cache_dir=cache_dir,
            device=device,
        ),
        "cure": _measure(
            "detecter.cure",
            resolved,
            image_id=image_id,
            sha256=sha256,
            cache_dir=cache_dir,
            device=device,
        ),
        "universal_fake_detect": _ufd_measure(
            resolved,
            image_id=image_id,
            sha256=sha256,
            detector=detectors.get("ufd"),
            cache_dir=cache_dir,
            device=device,
        ),
    }

    def raw(key: str) -> float | None:
        result = models[key]
        score = result.get("raw_score")
        if result.get("status") != "ok" or not isinstance(score, (int, float)):
            return None
        return float(score) if math.isfinite(score) else None

    cf_score, cure_score, ufd_score = (
        raw("community_forensics_384"),
        raw("cure"),
        raw("universal_fake_detect"),
    )
    try:
        base = calibrated_ai_probability(cf_score, cure_score, ufd_score)
    except ValueError:
        base = None

    category = device_category(exif)
    if jev_client is not None:
        final = final_ai_probability(
            jev_client,
            cf_score=cf_score,
            cure_score=cure_score,
            ufd_score=ufd_score,
            c2pa=c2pa,
            synthid=synthid,
            media=media,
            device_category=category,
            computational_photography_detected=bool(
                exif.get("computational_photography_detected")
            ),
        )
    else:
        final = {"status": "skipped", "reason": "jev_client_unavailable"}

    if base is None:
        probability = 0.0
        confidence = 0.0
        state = "inconclusive"
    elif final.get("status") == "ok":
        probability = float(final["final_ai_probability"])
        confidence = float(final["confidence"])
        state = str(final.get("ai_involvement") or "inconclusive")
    else:
        probability = float(base["probability"])
        confidence = 0.25 if base["partial"] else 0.5
        state = "jev_unavailable" if jev_client is None else "jev_error"
    probability = min(1.0, max(0.0, probability))

    record.update(
        ai_probability=round(probability, 6),
        ai_probability_percent=_percent(probability),
        confidence=round(min(1.0, max(0.0, confidence)), 6),
        state=state,
        bypass=None,
        breakdown={
            "c2pa": c2pa,
            "synthid": synthid,
            "raw_scores": {
                "community_forensics_384": cf_score,
                "cure": cure_score,
                "universal_fake_detect": ufd_score,
            },
            "models": models,
            "base_probability": base,
            "camera": exif.get("camera", {}),
            "device_category": category,
            "computational_photography_detected": bool(
                exif.get("computational_photography_detected")
            ),
            "jev": final,
        },
    )
    record["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return record


def _create_jev_client() -> Any:
    from typesafe_sdk import RetryPolicy, TypeSafeClient

    return TypeSafeClient(model=JEV_MODEL, retry=RetryPolicy(max_retries=0))


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="detecter analyze",
        description="画像を完全自動で解析し、統一JSONでAI確率を出力します。",
    )
    parser.add_argument("inputs", nargs="+", help="JPEG、PNG、WebP、HEIC、HEIFのパス")
    parser.add_argument(
        "--synthid-manual",
        type=Path,
        help="手動SynthID結果のJSON Lines。確定バイパスと内訳へ反映します。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("-"),
        help="追記するJSON Linesファイル。既定（'-'）は標準出力のみ。",
    )
    parser.add_argument("--cache-dir", type=Path, default=default_cache_dir())
    parser.add_argument("--device", choices=("auto", "cpu"), default="cpu")
    parser.add_argument(
        "--no-jev",
        action="store_true",
        help="Jev合成をスキップし、基底確率で確定します",
    )
    parser.add_argument(
        "--c2pa-trust-anchors",
        type=Path,
        help="C2PA署名者を信頼判定するPEMファイル",
    )
    parser.add_argument("--max-bytes", type=int, default=MAX_INPUT_BYTES)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.max_bytes <= 0:
        print("--max-bytes は1以上にしてください。", file=sys.stderr)
        return 2
    if args.device == "auto":
        args.device = "cpu"

    from .cli import collect_images

    images = collect_images(args.inputs)
    if not images:
        print("解析対象の画像がありません。", file=sys.stderr)
        return 2

    synthid_records = None
    if args.synthid_manual is not None:
        try:
            from .synthid_manual import read_manual_records

            synthid_records = read_manual_records(args.synthid_manual)
        except (OSError, ValueError) as error:
            print(f"SynthID手動結果を読み込めません: {error}", file=sys.stderr)
            return 2

    jev_client = None
    if not args.no_jev:
        try:
            jev_client = _create_jev_client()
        except Exception as error:  # noqa: BLE001
            print(
                f"Jevを準備できません（基底確率で続行します）: {type(error).__name__}",
                file=sys.stderr,
            )

    output_stream = None
    if str(args.output) != "-":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        output_stream = args.output.open("a", encoding="utf-8")

    detectors: dict[str, Any] = {}
    failed = False
    try:
        for image in images:
            try:
                record = analyze_image(
                    image,
                    device=args.device,
                    cache_dir=args.cache_dir,
                    c2pa_trust_anchors=args.c2pa_trust_anchors,
                    max_bytes=args.max_bytes,
                    jev_client=jev_client,
                    detectors=detectors,
                    synthid_records=synthid_records,
                )
            except Exception as error:  # noqa: BLE001 - one bad image must not abort
                failed = True
                record = {
                    "schema_version": SCHEMA_VERSION,
                    "image_id": str(image.expanduser().resolve()),
                    "ai_probability": None,
                    "ai_probability_percent": None,
                    "confidence": None,
                    "state": "error",
                    "error": f"{type(error).__name__}: {error}",
                }
            line = json.dumps(record, ensure_ascii=False, sort_keys=True)
            print(line)
            if output_stream:
                output_stream.write(line + "\n")
                output_stream.flush()
    finally:
        if output_stream:
            output_stream.close()
        close = getattr(jev_client, "close", None)
        if callable(close):
            close()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
