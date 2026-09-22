from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from .core import (
    MAX_INPUT_BYTES,
    UFD_DEFAULT_THRESHOLD,
    UfdDetector,
    analyze_full_area_tiles,
    analyze_image,
    build_jev_state,
    create_derived_jpeg,
    default_cache_dir,
    quantized_pixel_grid,
)

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
JEV_MODEL = "jev-1.13.0"
JEV_QUESTION_ID = "ai_involvement"
JEV_MAX_LOGICAL_IMAGES = 4
JEV_MAX_REQUESTS = 8
JEV_CHOICE_INSTRUCTIONS = "Based only on the forensic evidence in the state, which conclusion is best supported?"
JEV_CHOICE_CRITERIA = {
    "ai_involvement_likely": "The evidence supports likely AI generation or AI editing.",
    "inconclusive": "The evidence is incomplete, contradictory, or insufficient for either conclusion.",
    "no_ai_signal_detected": "The evidence contains no detected AI signal, without proving a real photograph.",
}


def collect_images(inputs: list[str]) -> list[Path]:
    images: list[Path] = []
    for value in inputs:
        path = Path(value).expanduser()
        if path.is_dir():
            images.extend(
                candidate
                for candidate in sorted(path.rglob("*"))
                if candidate.is_file() and candidate.suffix.lower() in IMAGE_SUFFIXES
            )
        else:
            images.append(path)
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in images:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return unique


def _choice_definition() -> dict[str, Any]:
    return {
        "type": "choice",
        "instructions": JEV_CHOICE_INSTRUCTIONS,
        "criteria": dict(JEV_CHOICE_CRITERIA),
    }


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _usage_record(usage: Any) -> dict[str, Any]:
    return {
        "input_tokens": _field(usage, "input_tokens"),
        "output_tokens": _field(usage, "output_tokens"),
    }


def _jev_error_record(
    state: dict[str, Any], started: float, error: BaseException
) -> dict[str, Any]:
    return {
        "state": state,
        "choice_definition": _choice_definition(),
        "requested_model": JEV_MODEL,
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "error_type": type(error).__name__,
        "http_status": _field(error, "status"),
        "request_id": _field(error, "request_id"),
    }


def run_jev_comparison(
    client: Any,
    states: dict[str, dict[str, Any]],
    *,
    setup_error: BaseException | None = None,
) -> tuple[dict[str, dict[str, Any]], bool]:
    """Run exactly one Choice request per condition and keep failures isolated."""
    results: dict[str, dict[str, Any]] = {}
    failed = False
    for condition, state in states.items():
        started = time.perf_counter()
        try:
            if setup_error is not None:
                raise setup_error
            from typesafe_sdk import Choice

            response = client.system_one(
                state=state,
                questions={
                    JEV_QUESTION_ID: Choice(
                        instructions=JEV_CHOICE_INSTRUCTIONS,
                        criteria=JEV_CHOICE_CRITERIA,
                    )
                },
            )
            answers = _field(response, "answers", {})
            answer = answers[JEV_QUESTION_ID]
            probabilities = dict(_field(answer, "probabilities", {}))
            results[condition] = {
                "state": state,
                "choice_definition": _choice_definition(),
                "choice": _field(answer, "choice"),
                "probabilities": probabilities,
                "confidence": _field(answer, "confidence"),
                "requested_model": JEV_MODEL,
                "actual_model": _field(response, "model"),
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                "usage": _usage_record(_field(response, "usage")),
                "request_id": _field(response, "request_id"),
            }
        except Exception as error:  # noqa: BLE001
            failed = True
            results[condition] = _jev_error_record(state, started, error)
    return results, failed


def _local_jev_error_comparison(error: BaseException) -> dict[str, Any]:
    conditions = {
        condition: {
            "choice_definition": _choice_definition(),
            "requested_model": JEV_MODEL,
            "error_type": type(error).__name__,
            "http_status": None,
            "request_id": None,
        }
        for condition in ("A", "B")
    }
    return {"model": JEV_MODEL, "conditions": conditions}


def _create_jev_client() -> Any:
    from typesafe_sdk import RetryPolicy, TypeSafeClient

    return TypeSafeClient(model=JEV_MODEL, retry=RetryPolicy(max_retries=0))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="detecter",
        description="C2PAとUniversalFakeDetectで画像を試験解析します。",
    )
    subcommands = root.add_subparsers(dest="command", required=True)
    analyze = subcommands.add_parser(
        "analyze", help="画像またはディレクトリを解析します"
    )
    analyze.add_argument("inputs", nargs="+", help="JPEG、PNG、WebPのパス")
    analyze.add_argument(
        "--output",
        type=Path,
        default=Path("results/detections.jsonl"),
        help="追記するJSON Linesファイル。'-'ならファイルへ保存しません。",
    )
    analyze.add_argument("--cache-dir", type=Path, default=default_cache_dir())
    analyze.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    analyze.add_argument("--threshold", type=float, default=UFD_DEFAULT_THRESHOLD)
    analyze.add_argument("--skip-c2pa", action="store_true")
    analyze.add_argument(
        "--c2pa-trust-anchors",
        type=Path,
        help="C2PA署名者を信頼判定するPEMファイル",
    )
    analyze.add_argument("--skip-ufd", action="store_true")
    analyze.add_argument("--max-bytes", type=int, default=MAX_INPUT_BYTES)
    analyze.add_argument(
        "--jev-compare",
        action="store_true",
        help="Jev 1.13で画素グリッド追加前後の比較を記録します",
    )
    analyze.add_argument(
        "--jev-derived-jpeg-of",
        type=Path,
        help="指定画像からEXIF回転・長辺1024px・JPEG品質75の一時画像を作ります",
    )
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    images = collect_images(args.inputs)
    if not images:
        print("解析対象の画像がありません。", file=sys.stderr)
        return 2
    if not 0 <= args.threshold <= 1:
        print("--threshold は0以上1以下にしてください。", file=sys.stderr)
        return 2
    if args.max_bytes <= 0:
        print("--max-bytes は1以上にしてください。", file=sys.stderr)
        return 2
    if args.jev_compare and args.skip_ufd:
        print("--jev-compare と --skip-ufd は併用できません。", file=sys.stderr)
        return 2

    derived_directory = (
        tempfile.TemporaryDirectory(prefix="detecter-jev-")
        if args.jev_derived_jpeg_of is not None
        else None
    )
    jev_client = None
    jev_setup_error: BaseException | None = None
    try:
        logical_images: list[tuple[Path, str, Path]] = [
            (image, "original", image) for image in images
        ]
        if args.jev_derived_jpeg_of is not None:
            derived_source = args.jev_derived_jpeg_of.expanduser().resolve()
            source_matches = [
                image
                for image in images
                if image.expanduser().resolve() == derived_source
            ]
            if not source_matches:
                print(
                    "--jev-derived-jpeg-of は入力画像の一つを指定してください。",
                    file=sys.stderr,
                )
                return 2
            try:
                derived = create_derived_jpeg(
                    derived_source,
                    directory=Path(derived_directory.name),
                    max_bytes=args.max_bytes,
                )
            except Exception as error:  # noqa: BLE001
                print(
                    f"加工版JPEGを作成できません: {type(error).__name__}",
                    file=sys.stderr,
                )
                return 1
            logical_images.append((derived, "derived_jpeg", derived_source))

        if args.jev_compare and len(logical_images) > JEV_MAX_LOGICAL_IMAGES:
            print(
                f"--jev-compare は最大{JEV_MAX_LOGICAL_IMAGES}論理画像です。",
                file=sys.stderr,
            )
            return 2
        if args.jev_compare and len(logical_images) * 2 > JEV_MAX_REQUESTS:
            print(
                f"--jev-compare のAPIリクエストは最大{JEV_MAX_REQUESTS}回です。",
                file=sys.stderr,
            )
            return 2

        detector = None
        if not args.skip_ufd:
            print("UniversalFakeDetectを準備しています…", file=sys.stderr)
            try:
                detector = UfdDetector(cache_dir=args.cache_dir, device=args.device)
            # CLI boundary: dependency, download, and device failures need one clear error.
            except Exception as error:  # noqa: BLE001
                print(f"UniversalFakeDetectを準備できません: {error}", file=sys.stderr)
                return 1

        if args.jev_compare:
            try:
                jev_client = _create_jev_client()
            except Exception as error:  # noqa: BLE001
                jev_setup_error = error
                print(
                    f"Jevを準備できません: {type(error).__name__}",
                    file=sys.stderr,
                )

        output_stream = None
        if str(args.output) != "-":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            output_stream = args.output.open("a", encoding="utf-8")

        failed = False
        try:
            for image, input_variant, display_path in logical_images:
                try:
                    record = analyze_image(
                        image,
                        detector=detector,
                        threshold=args.threshold,
                        check_c2pa=not args.skip_c2pa,
                        c2pa_trust_anchors=args.c2pa_trust_anchors,
                        max_bytes=args.max_bytes,
                    )
                # A bad image must not prevent the remaining input files from being recorded.
                except Exception as error:  # noqa: BLE001
                    failed = True
                    record = {
                        "schema_version": 1,
                        "path": str(image.expanduser().resolve()),
                        "error": f"{type(error).__name__}: {error}",
                    }
                record["input_variant"] = input_variant
                if input_variant == "derived_jpeg":
                    record["path"] = str(display_path.expanduser().resolve())

                if args.jev_compare:
                    if "error" in record:
                        failed = True
                        record["jev_comparison"] = _local_jev_error_comparison(
                            RuntimeError("LocalAnalysisError")
                        )
                    else:
                        try:
                            tile_result = analyze_full_area_tiles(
                                image,
                                detector,
                                threshold=args.threshold,
                                max_bytes=args.max_bytes,
                            )
                            record["universal_fake_detect_tiles"] = tile_result
                            state_a = build_jev_state(
                                record["media"],
                                record["c2pa"],
                                tile_result,
                                input_variant=input_variant,
                            )
                            state_b = deepcopy(state_a)
                            state_b["pixel_grid"] = quantized_pixel_grid(image)
                            jev_results, jev_failed = run_jev_comparison(
                                jev_client,
                                {"A": state_a, "B": state_b},
                                setup_error=jev_setup_error,
                            )
                            failed = failed or jev_failed
                            record["jev_comparison"] = {
                                "model": JEV_MODEL,
                                "conditions": jev_results,
                            }
                        except Exception as error:  # noqa: BLE001
                            failed = True
                            record["jev_comparison"] = _local_jev_error_comparison(
                                error
                            )

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
    finally:
        if derived_directory is not None:
            derived_directory.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
