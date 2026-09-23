"""Record a user's SynthID screen result without sending or verifying images."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from detecter.core import inspect_image

STATES = ("detected", "not_detected", "not_checked", "unverifiable")
SCOPES = ("unknown", "full", "partial")

INTERPRETATIONS = {
    "detected": (
        "SynthID検出はGoogleのAIによる生成または編集の証拠です。"
        "画像全体の生成確定ではありません。"
    ),
    "not_detected": (
        "SynthID未検出は実写の証明ではなく、"
        "他社AIによる生成・編集の否定にもなりません。"
    ),
    "not_checked": "SynthIDは未検査です。",
    "unverifiable": "SynthIDの確認を試みましたが、結果を確認できませんでした。",
}


def create_manual_record(
    image: Path,
    *,
    image_id: str,
    sha256: str,
    state: str,
    registrant: str,
    checked_at: str | None = None,
    route: str | None = None,
    evidence: str | None = None,
    generation_scope: str = "unknown",
) -> dict[str, Any]:
    """Validate a manual result against the local image before storing it."""
    if not image_id.strip() or not registrant.strip():
        raise ValueError("画像IDと手動登録者または登録元は必須です")
    if re.fullmatch(r"[0-9a-f]{64}", sha256) is None:
        raise ValueError("SHA-256は小文字の16進数64文字で指定してください")
    if state not in STATES or generation_scope not in SCOPES:
        raise ValueError("確認状態または生成範囲が不正です")
    if state != "detected" and generation_scope != "unknown":
        raise ValueError("検出されていない結果から生成範囲を指定できません")
    if state == "not_checked":
        if any(value is not None for value in (checked_at, route, evidence)):
            raise ValueError(
                "未検査の記録に確認日時・確認経路・画面の根拠は指定できません"
            )
    else:
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (checked_at, route, evidence)
        ):
            raise ValueError("確認日時・確認経路・画面の根拠は必須です")
        checked = datetime.fromisoformat(str(checked_at))
        if checked.tzinfo is None or checked.utcoffset() is None:
            raise ValueError("確認日時にはタイムゾーンを含めてください")
        checked_at = checked.astimezone(UTC).isoformat()
    resolved = image.expanduser().resolve()
    if inspect_image(resolved)["sha256"] != sha256:
        raise ValueError("画像のSHA-256が一致しません。別画像の結果は登録できません")
    return {
        "schema_version": 1,
        "image_id": image_id,
        "sha256": sha256,
        "path": str(resolved),
        "state": state,
        "manual": True,
        "automatically_verified": False,
        "signature_state": "not_checked",
        "binding_state": "match",
        "generation_scope": generation_scope,
        "checked_at": checked_at,
        "route": route,
        "evidence": evidence,
        "registrant": registrant,
        "registered_at": datetime.now(UTC).isoformat(),
    }


def read_manual_records(path: Path) -> list[dict[str, Any]]:
    """Read saved manual results without revalidating the image files."""
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: expected object")  # noqa: TRY004
            records.append(row)
    return records


def find_manual_record(
    records: Sequence[Mapping[str, Any]] | None,
    *,
    image_id: str,
    sha256: str,
) -> dict[str, Any] | None:
    """Return the latest record bound to both the image ID and the SHA-256."""
    matched: dict[str, Any] | None = None
    for record in records or []:
        if not isinstance(record, dict):
            continue
        if record.get("image_id") == image_id and record.get("sha256") == sha256:
            matched = record
    return matched


def summarize_synthid(
    *,
    image_id: str,
    sha256: str,
    records: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the report section for a manual SynthID result.

    Only a record matching both the image ID and the SHA-256 is linked.
    The summary never claims automatic verification and never touches
    the C2PA signature, trust, or binding states.
    """
    matched = find_manual_record(records, image_id=image_id, sha256=sha256)
    if matched is None:
        reason = "synthid_manual_not_registered"
        if isinstance(records, Sequence):
            for record in records:
                if isinstance(record, dict) and record.get("image_id") == image_id:
                    reason = "synthid_hash_mismatch"
                    break
        return {
            "status": "not_linked",
            "state": "not_checked",
            "manual": False,
            "automatically_verified": False,
            "reason": reason,
        }
    state = matched.get("state")
    if state not in STATES:
        state = "unverifiable"
    scope = matched.get("generation_scope")
    if scope not in SCOPES or (state != "detected" and scope != "unknown"):
        scope = "unknown"
    return {
        "status": "linked",
        "state": state,
        "manual": True,
        "automatically_verified": False,
        "signature_state": "not_checked",
        "binding_state": "match",
        "generation_scope": scope,
        "image_id": image_id,
        "sha256": sha256,
        "checked_at": matched.get("checked_at"),
        "route": matched.get("route"),
        "evidence": matched.get("evidence"),
        "registrant": matched.get("registrant"),
        "interpretation": INTERPRETATIONS[state],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="SynthIDの公式画面を手動で確認した結果を登録します。"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add", help="画像と照合して手動記録を追記します")
    add.add_argument("--image", type=Path, required=True)
    add.add_argument("--image-id", required=True)
    add.add_argument("--sha256", required=True)
    add.add_argument("--state", choices=STATES, required=True)
    add.add_argument("--checked-at")
    add.add_argument("--route")
    add.add_argument(
        "--evidence", type=Path, help="画面で得た根拠を記したUTF-8テキストファイル"
    )
    add.add_argument("--registrant", required=True, help="手動登録者または登録元")
    add.add_argument("--generation-scope", choices=SCOPES, default="unknown")
    add.add_argument(
        "--output", type=Path, default=Path("results/synthid-manual.jsonl")
    )
    args = parser.parse_args(argv)
    try:
        record = create_manual_record(
            args.image,
            image_id=args.image_id,
            sha256=args.sha256,
            state=args.state,
            registrant=args.registrant,
            checked_at=args.checked_at,
            route=args.route,
            evidence=args.evidence.read_text(encoding="utf-8")
            if args.evidence is not None
            else None,
            generation_scope=args.generation_scope,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
