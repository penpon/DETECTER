"""Four existing images, two vision conditions, eight requests without retries."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx2
from PIL import Image, ImageOps
from typesafe_sdk import SystemOneResponse

from detecter.cli import JEV_CHOICE_CRITERIA
from detecter.core import inspect_image, summarize_c2pa

ROOT = Path(__file__).resolve().parents[1]
CASES = (
    ("jev-camera-comparison.jsonl", "samples/generated/gpt_image_2_5.png"),
    ("jev-camera-comparison.jsonl", "samples/generated/nano_banana_2.png"),
    ("jev-camera-comparison.jsonl", "samples/real/DSC07518.jpg"),
    ("jev-iphone-camera-comparison.jsonl", "samples/real/IMG_0214_camera.jpg"),
)
QUESTION = {
    "type": "choice",
    "instructions": (
        "Examine the attached image and any forensic evidence in the state. "
        "Which conclusion about AI generation or AI editing is best supported? "
        "Routine camera processing, photographic editing, noise, and JPEG artifacts "
        "alone do not establish generative AI involvement. "
        "When evidence is insufficient, choose inconclusive."
    ),
    "criteria": JEV_CHOICE_CRITERIA,
}


def prepare_case(evidence_path: Path, image_path: Path) -> dict:
    media = inspect_image(image_path)
    records = [json.loads(line) for line in evidence_path.read_text().splitlines()]
    record = next(
        r
        for r in reversed(records)
        if r.get("input_variant") == "original"
        and r.get("media", {}).get("sha256") == media["sha256"]
    )
    tiles = record["universal_fake_detect_tiles"]
    if tiles["status"] != "ok":
        raise ValueError("Full-area detector evidence is incomplete")
    with Image.open(image_path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.info.clear()
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85, exif=b"", icc_profile=None)
    blob = buffer.getvalue()
    if len(blob) > 5 * 1024 * 1024:
        raise ValueError("The metadata-free JPEG exceeds the service's 5 MiB limit")
    state = {
        "image_preprocessing": {
            "width": image.width,
            "height": image.height,
            "exif_orientation_applied": True,
            "jpeg_quality": 85,
            "resized": False,
            "metadata_removed": True,
        },
        "limitations": [
            "SynthID was not checked.",
            "No AI signal is not proof of camera origin.",
        ],
    }
    return {
        "path": str(image_path),
        "source_sha256": media["sha256"],
        "evidence_file": str(evidence_path),
        "image": {
            "sha256": hashlib.sha256(blob).hexdigest(),
            "bytes": len(blob),
            **state["image_preprocessing"],
        },
        "data_url": "data:image/jpeg;base64," + base64.b64encode(blob).decode(),
        "states": {
            "image_only": state,
            "image_with_evidence": {
                **state,
                "forensics": {
                    "c2pa": summarize_c2pa(record["c2pa"]),
                    "universal_fake_detect": tiles,
                    "limitations": [
                        "Evidence was measured on the source before transport re-encoding.",
                        "UFD scores are uncalibrated, not probabilities of correctness.",
                        "All tiles use the same detector, not independent detectors.",
                    ],
                },
            },
        },
    }


def compare(client, endpoint: str, model: str, cases: list[dict], output) -> int:
    if not 1 <= len(cases) <= 4:
        raise ValueError("Use 1 to 4 images; the limit is 8 requests")
    failed = False
    for case in cases:
        for condition in ("image_only", "image_with_evidence"):
            payload = {
                "model": model,
                "state": case["states"][condition],
                "images": [case["data_url"]],
                "questions": {"ai_involvement": QUESTION},
                "samples": 1,
                "steps": 1,
            }
            result = {k: v for k, v in case.items() if k not in {"data_url", "states"}}
            result.update(
                condition=condition,
                endpoint=endpoint,
                request={k: v for k, v in payload.items() if k != "images"},
                started_at=datetime.now(UTC).isoformat(),
            )
            started = time.perf_counter()
            response = None
            try:
                response = client.post(endpoint, json=payload)
                response.raise_for_status()
                parsed = SystemOneResponse.model_validate(response.json())
                answer = parsed.choices["ai_involvement"]
                if set(answer.probabilities) != set(JEV_CHOICE_CRITERIA):
                    raise ValueError("Unexpected response choices")
                result["response"] = parsed.model_dump(mode="json")
            except Exception as error:  # noqa: BLE001
                failed = True
                # Do not persist exception text or response bodies: they can echo secrets.
                result["error_type"] = type(error).__name__
            result["http_status"] = (
                response.status_code if response is not None else None
            )
            result["request_id"] = (
                response.headers.get("x-request-id") if response is not None else None
            )
            result["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
            output.write(json.dumps(result, ensure_ascii=False) + "\n")
            output.flush()
            print(
                f"{Path(case['path']).name} {condition}: {result.get('error_type', 'ok')}"
            )
    return int(failed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Prepare and check images without network requests",
    )
    parser.add_argument("--endpoint", default="https://api.codiv.ai/v1/systemone")
    parser.add_argument("--model", default="openjev-0.1")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    cases = [
        prepare_case(ROOT / "results" / evidence, ROOT / image)
        for evidence, image in CASES
    ]
    if args.dry_run:
        for case in cases:
            print(json.dumps({"path": case["path"], "image": case["image"]}))
        print("Ready: 4 images, 8 requests; no requests sent")
        return 0
    key = os.environ.get("CODIV_API_KEY", "").strip()
    if not key or key.startswith("op://"):
        parser.error("Inject CODIV_API_KEY via op run before executing")
    url = httpx2.URL(args.endpoint)
    if (
        url.scheme != "https"
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        parser.error("Use an HTTPS endpoint without credentials or query parameters")
    output_path = (
        args.output or ROOT / "results" / f"diffusiongemma-{time.time_ns()}.jsonl"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with (
        output_path.open("x", encoding="utf-8") as output,
        httpx2.Client(
            headers={"Authorization": f"Bearer {key}"},
            timeout=60,
            follow_redirects=False,
        ) as client,
    ):
        return compare(client, str(url), args.model, cases, output)


if __name__ == "__main__":
    raise SystemExit(main())
