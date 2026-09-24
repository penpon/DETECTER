"""Measure OpenAI Content Provenance on a ledger of images and keep raw JSONL."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from detecter.openai_provenance import (
    aggregate,
    classify_condition,
    generator_name,
    measure,
)
from detecter.ufd_batch import load_inputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="OpenAI Content Provenance APIで台帳の画像を計測します。"
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY"))
    parser.add_argument(
        "--base-url", default="https://api.openai.com/v1/content_provenance_checks"
    )
    parser.add_argument(
        "--local-fallback",
        action="store_true",
        help="APIキーがない場合はローカルC2PAリーダーで代替計測する",
    )
    parser.add_argument("--sleep", type=float, default=0.5, help="API呼び出し間の秒数")
    args = parser.parse_args(argv)

    inputs = load_inputs(args.ledger)
    output = args.output.expanduser().resolve()
    if output.exists():
        raise ValueError(f"出力先に既存ファイルがあります: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    errors = 0
    for row in inputs:
        record = measure(
            Path(row["path"]),
            image_id=row["image_id"],
            expected_sha256=row["sha256"],
            api_key=args.api_key,
            base_url=args.base_url,
            local_fallback=args.local_fallback,
        )
        record.update(
            source_image_id=row.get("source_image_id", row["image_id"]),
            source_sha256=row.get("source_sha256", row["sha256"]),
            history=row.get("history", []),
        )
        record["generator"] = row.get("generator") or generator_name(record)
        record["condition"] = row.get("condition") or classify_condition(
            record["history"]
        )
        records.append(record)

        if record["status"] not in ("ok", "local_fallback"):
            errors += 1
        if args.api_key and record["status"] == "ok" and args.sleep > 0:
            time.sleep(args.sleep)

    with output.open("x", encoding="utf-8") as stream:
        for record in records:
            stream.write(
                json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False)
                + "\n"
            )

    summary = aggregate(records)
    summary_path = output.with_suffix(".summary.json")
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "images": len(records),
                "errors": errors,
                "output": str(output),
                "summary": str(summary_path),
            },
            ensure_ascii=False,
        )
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
