"""Independent C2PA provenance records, without model inference or labels."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from detecter.core import inspect_c2pa, inspect_image


def inspect_provenance(
    path: Path,
    *,
    image_id: str,
    expected_sha256: str | None = None,
    check: bool = True,
    trust_anchors: Path | None = None,
) -> dict[str, Any]:
    """Bind an independent provenance result to an image ID and the file hash."""
    if not image_id.strip():
        raise ValueError("image_id は空にできません")
    if (
        expected_sha256 is not None
        and re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
    ):
        raise ValueError("sha256 は小文字の16進数64文字で指定してください")
    resolved = path.expanduser().resolve()
    media = inspect_image(resolved)
    result: dict[str, Any] = {
        "schema_version": 1,
        "image_id": image_id,
        "sha256": media["sha256"],
        "path": str(resolved),
        **inspect_c2pa(resolved, trust_anchors=trust_anchors, check=check),
    }
    if expected_sha256 is not None:
        result["expected_sha256"] = expected_sha256
        if expected_sha256 != media["sha256"]:
            result.update(
                binding_state="mismatch",
                confirmation_state="hash_mismatch",
                confirmed=False,
            )
            result["reasons"].append("input_sha256_mismatch")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="C2PAの署名・信頼・画像との一致を確認します。"
    )
    parser.add_argument("image", type=Path)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--sha256", help="評価台帳で期待する画像ファイルのSHA-256")
    parser.add_argument("--c2pa-trust-anchors", type=Path)
    parser.add_argument("--skip-c2pa", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("-"),
        help="追記先のJSON Linesファイル。'-'は標準出力のみ。",
    )
    args = parser.parse_args(argv)
    try:
        record = inspect_provenance(
            args.image,
            image_id=args.image_id,
            expected_sha256=args.sha256,
            check=not args.skip_c2pa,
            trust_anchors=args.c2pa_trust_anchors,
        )
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        if str(args.output) != "-":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
        print(line)
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 1 if record["status"] == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
