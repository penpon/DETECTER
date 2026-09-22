"""Independent JPEG quality and lossless resize conditions for evaluation images."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps
from PIL import __version__ as PILLOW_VERSION

from .core import inspect_image
from .ledger import read_ledger

PREPROCESSING_VERSION = "derive-jpeg-and-resize-v1"


def derive_images(
    ledger: Path | str,
    directory: Path | str,
    *,
    qualities: Sequence[int] = (95, 85, 75),
    long_sides: Sequence[int] = (1024, 512),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return unique derived ledger rows and one record per requested condition."""
    for values in (qualities, long_sides):
        if any(type(value) is not int or value < 1 for value in values) or len(
            set(values)
        ) != len(values):
            raise ValueError("加工条件には重複なしの正の整数を指定してください")
    if any(quality > 100 for quality in qualities):
        raise ValueError("JPEG品質は1以上100以下を指定してください")
    if not qualities and not long_sides:
        raise ValueError("少なくとも1つの加工条件を指定してください")
    rows = read_ledger(ledger)
    directory = Path(directory).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=False)
    derived = []
    conditions = []
    by_hash = {row["sha256"]: (row["image_id"], row["source_group"]) for row in rows}
    requested = [("jpeg", quality) for quality in qualities] + [
        ("resize", size) for size in long_sides
    ]
    for row in sorted(rows, key=lambda item: item["image_id"]):
        inspect_image(Path(row["path"]))
        with Image.open(row["path"]) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
        image.info.clear()
        for operation, value in requested:
            converted = image.copy()
            if operation == "resize":
                converted.thumbnail(
                    (value, value), Image.Resampling.LANCZOS, reducing_gap=None
                )
            quality = value if operation == "jpeg" else None
            image_format = "JPEG" if operation == "jpeg" else "PNG"
            transform = {
                "operation": operation,
                "preprocessing_version": PREPROCESSING_VERSION,
                "pillow": PILLOW_VERSION,
                "exif_transpose": True,
                "color_mode": "RGB",
                "jpeg_quality": quality,
                "long_side": value if operation == "resize" else None,
                "interpolation": "LANCZOS" if operation == "resize" else None,
                "format": image_format,
                "output_size": list(converted.size),
                "subsampling": 0 if operation == "jpeg" else None,
                "optimize": False,
                "progressive": False,
                "png_compress_level": 6 if operation == "resize" else None,
            }
            buffer = io.BytesIO()
            if operation == "jpeg":
                converted.save(
                    buffer,
                    format="JPEG",
                    quality=quality,
                    subsampling=0,
                    optimize=False,
                    progressive=False,
                )
            else:
                converted.save(buffer, format="PNG", compress_level=6, optimize=False)
            content = buffer.getvalue()
            digest = hashlib.sha256(content).hexdigest()
            existing = by_hash.get(digest)
            if existing is not None and existing[1] != row["source_group"]:
                raise ValueError(
                    f"異なる元画像グループの加工結果が同じハッシュです: {row['image_id']}"
                )
            image_id = existing[0] if existing else None
            status = "unchanged" if digest == row["sha256"] else "duplicate"
            if image_id is None:
                image_id = (
                    "derived-"
                    + hashlib.sha256(
                        f"{row['image_id']}\0{operation}-{value}".encode()
                    ).hexdigest()
                )
                target = (
                    directory / f"{image_id}.{'jpg' if operation == 'jpeg' else 'png'}"
                )
                with target.open("xb") as stream:
                    stream.write(content)
                derived.append(
                    {
                        **row,
                        "image_id": image_id,
                        "path": str(target),
                        "sha256": digest,
                        "source_image_id": row["image_id"],
                        "source_sha256": row["sha256"],
                        "history": [*row["history"], transform],
                    }
                )
                by_hash[digest] = (image_id, row["source_group"])
                status = "created"
            conditions.append(
                {
                    "source_image_id": row["image_id"],
                    "source_sha256": row["sha256"],
                    "source_group": row["source_group"],
                    "condition": transform,
                    "image_id": image_id,
                    "sha256": digest,
                    "status": status,
                }
            )
    return derived, conditions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="JPEG品質と縮小の独立した加工条件を生成します"
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--qualities", default="95,85,75")
    parser.add_argument("--long-sides", default="1024,512")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        output = args.output.expanduser().resolve()
        condition_output = output.with_suffix(".conditions.jsonl")
        if output == condition_output or output.exists() or condition_output.exists():
            raise ValueError(
                "出力先には既存ファイルと異なる新しい台帳名を指定してください"
            )
        derived, conditions = derive_images(
            args.ledger,
            output.parent / f"{output.stem}.images",
            qualities=[int(value) for value in args.qualities.split(",") if value],
            long_sides=[int(value) for value in args.long_sides.split(",") if value],
        )
        for path, records in ((output, derived), (condition_output, conditions)):
            with path.open("x", encoding="utf-8") as stream:
                for record in records:
                    stream.write(
                        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
                    )
        print(
            json.dumps(
                {
                    "images": len(derived),
                    "conditions": len(conditions),
                    "ledger": str(output),
                    "condition_records": str(condition_output),
                }
            )
        )
    except (ValueError, OSError) as error:
        print(f"画像加工に失敗しました: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
