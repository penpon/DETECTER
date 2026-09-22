from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core import (
    MAX_INPUT_BYTES,
    UFD_DEFAULT_THRESHOLD,
    UfdDetector,
    analyze_image,
    default_cache_dir,
)

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


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

    detector = None
    if not args.skip_ufd:
        print("UniversalFakeDetectを準備しています…", file=sys.stderr)
        try:
            detector = UfdDetector(cache_dir=args.cache_dir, device=args.device)
        # CLI boundary: dependency, download, and device failures need one clear error.
        except Exception as error:  # noqa: BLE001
            print(f"UniversalFakeDetectを準備できません: {error}", file=sys.stderr)
            return 1

    output_stream = None
    if str(args.output) != "-":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        output_stream = args.output.open("a", encoding="utf-8")

    failed = False
    try:
        for image in images:
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
            line = json.dumps(record, ensure_ascii=False, sort_keys=True)
            print(line)
            if output_stream:
                output_stream.write(line + "\n")
                output_stream.flush()
    finally:
        if output_stream:
            output_stream.close()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
