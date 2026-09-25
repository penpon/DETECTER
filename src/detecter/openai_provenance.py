"""OpenAI Content Provenance API measurements with an optional local C2PA fallback."""

from __future__ import annotations

import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4

from .core import inspect_c2pa, inspect_image

API_URL = "https://api.openai.com/v1/content_provenance_checks"
API_TIMEOUT = 60
MAX_RETRIES = 8
SUPPORTED_TYPES = {"image/png", "image/jpeg", "image/webp"}
_SLEEP_BASE = 2.0


def _media_type(path: Path) -> str:
    mapping = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }
    return (
        mapping.get(path.suffix.lower())
        or mimetypes.guess_type(str(path))[0]
        or "application/octet-stream"
    )


def _encode_multipart(path: Path, boundary: str) -> bytes:
    data = path.read_bytes()
    mime = _media_type(path)
    parts: list[bytes] = [
        f"--{boundary}\r\n".encode("latin-1"),
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode(
            "latin-1"
        ),
        f"Content-Type: {mime}\r\n\r\n".encode("latin-1"),
        data,
        f"\r\n--{boundary}--\r\n".encode("latin-1"),
    ]
    return b"".join(parts)


def _sleep_for_retry(attempt: int, retry_after: float | None = None) -> None:
    delay = (
        retry_after if retry_after and retry_after > 0 else _SLEEP_BASE * (attempt + 1)
    )
    time.sleep(delay)


def request_openai_provenance(
    path: Path,
    *,
    api_key: str,
    base_url: str = API_URL,
    timeout: float = API_TIMEOUT,
    max_retries: int = MAX_RETRIES,
) -> dict[str, Any]:
    """POST a single image to the OpenAI Content Provenance API and retry 429/timeouts."""
    mime = _media_type(path)
    if mime not in SUPPORTED_TYPES:
        return {
            "api_status": "unsupported_format",
            "error": f"unsupported media type {mime}",
        }

    boundary = uuid4().hex
    body = _encode_multipart(path, boundary)
    request = urllib.request.Request(
        base_url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )

    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                parsed = json.loads(raw)
                if not isinstance(parsed, dict):
                    return {
                        "api_status": "invalid_response",
                        "error": "response is not an object",
                    }
                parsed["api_status"] = "ok"
                return parsed
        except urllib.error.HTTPError as error:
            if error.code == 429 and attempt < max_retries - 1:
                try:
                    retry_after = float(error.headers.get("Retry-After", 0))
                except (TypeError, ValueError):
                    retry_after = None
                _sleep_for_retry(attempt, retry_after)
                continue
            return {
                "api_status": f"http_{error.code}",
                "error": f"{error.code}: {error.reason}",
            }
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            if attempt < max_retries - 1:
                _sleep_for_retry(attempt)
                continue
            return {
                "api_status": "network_error",
                "error": f"{type(error).__name__}: {error}",
            }
        except json.JSONDecodeError as error:
            return {"api_status": "json_error", "error": str(error)}

    return {"api_status": "max_retries", "error": "max retries exceeded"}


def summarize_openai_response(response: dict[str, Any]) -> dict[str, Any]:
    """Extract C2PA and SynthID outcomes from an OpenAPI provenance response."""
    c2pa: dict[str, Any] = {
        "outcome": "not_detected",
        "validation_state": None,
        "issuer": None,
        "model": None,
        "generated_at": None,
    }
    synthid: dict[str, Any] = {
        "outcome": "not_detected",
        "model": None,
        "generated_at": None,
    }
    for item in response.get("results", []):
        if not isinstance(item, dict):
            continue
        if item.get("type") == "c2pa":
            c2pa["outcome"] = item.get("outcome", "not_detected")
            c2pa["validation_state"] = item.get("validation_state")
            c2pa["issuer"] = item.get("issuer")
            c2pa["model"] = item.get("model")
            c2pa["generated_at"] = item.get("generated_at")
        elif item.get("type") == "synthid":
            synthid["outcome"] = item.get("outcome", "not_detected")
            synthid["model"] = item.get("model")
            synthid["generated_at"] = item.get("generated_at")
    return {"c2pa": c2pa, "synthid": synthid}


def classify_condition(history: list[dict[str, Any]]) -> str:
    """Return a short condition label from a ledger history list."""
    if not history:
        return "original"

    ops = [
        (
            item.get("operation"),
            item.get("jpeg_quality"),
            item.get("long_side"),
            item.get("name"),
        )
        for item in history
        if isinstance(item, dict)
    ]
    has_resize_1024 = any(
        op == "resize" and long_side == 1024 for op, _, long_side, _ in ops
    )
    has_jpeg_75 = any(op == "jpeg" and quality == 75 for op, quality, _, _ in ops)
    if has_resize_1024 and has_jpeg_75:
        return "sns-q75"

    explicit = [name for _, _, _, name in ops if isinstance(name, str) and name]
    if explicit:
        return explicit[-1]

    tokens = [f"{op}{value or ''}" for op, value, _, _ in ops if op]
    return "-".join(tokens) if tokens else "original"


def generator_name(record: dict[str, Any]) -> str:
    """Infer a generator label from a record when one is not already supplied."""
    if record.get("generator"):
        return record["generator"]
    name = Path(record.get("path", "")).name.lower()
    if "gpt" in name or "dall" in name:
        return "gpt-image-2"
    if "nano" in name or "banana" in name:
        return "nano-banana"
    if "img_" in name or "iphone" in name:
        return "iphone-real"
    return "unknown"


def _local_c2pa_detected(local_c2pa: dict[str, Any] | None) -> bool:
    if not isinstance(local_c2pa, dict):
        return False
    return local_c2pa.get("status") == "present" and bool(
        local_c2pa.get("ai_source_assertion")
    )


def measure(
    path: Path,
    *,
    image_id: str | None = None,
    expected_sha256: str | None = None,
    api_key: str | None = None,
    base_url: str = API_URL,
    local_fallback: bool = False,
) -> dict[str, Any]:
    """Measure one image with the API, or fall back to the local C2PA reader."""
    resolved = path.expanduser().resolve()
    media = inspect_image(resolved)
    actual_sha256 = media["sha256"]

    record: dict[str, Any] = {
        "schema_version": 1,
        "image_id": image_id or str(resolved),
        "sha256": expected_sha256,
        "path": str(resolved),
        "format": media["format"],
        "width": media["width"],
        "height": media["height"],
        "bytes": media["bytes"],
        "status": "error",
        "api_status": None,
        "openai": None,
        "local_c2pa": None,
        "error": None,
    }

    try:
        if expected_sha256 is not None and actual_sha256 != expected_sha256:
            raise ValueError("image hash mismatch")
        record["sha256"] = actual_sha256

        key = api_key or os.environ.get("OPENAI_API_KEY")
        if key:
            response = request_openai_provenance(
                resolved, api_key=key, base_url=base_url
            )
            record["api_status"] = response.get("api_status")
            if response.get("api_status") == "ok":
                record["openai"] = summarize_openai_response(response)
                record["status"] = "ok"
            else:
                record["error"] = response.get("error")
                if local_fallback:
                    record["local_c2pa"] = inspect_c2pa(resolved)
                    record["status"] = "local_fallback"
        else:
            record["api_status"] = "api_key_missing"
            if local_fallback:
                record["local_c2pa"] = inspect_c2pa(resolved)
                record["status"] = "local_fallback"
            else:
                raise ValueError("OPENAI_API_KEY is not set")
    except Exception as error:  # noqa: BLE001 -- every image needs a record
        record["error"] = f"{type(error).__name__}: {error}"

    return record


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate detection counts by generator and condition."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in records:
        gen = record.get("generator") or generator_name(record)
        cond = record.get("condition") or classify_condition(record.get("history", []))
        groups.setdefault((gen, cond), []).append(record)

    rows = []
    for (gen, cond), group in sorted(groups.items()):
        total = len(group)
        c2pa_detected = sum(
            1
            for r in group
            if (r.get("openai") or {}).get("c2pa", {}).get("outcome") == "detected"
        )
        synthid_detected = sum(
            1
            for r in group
            if (r.get("openai") or {}).get("synthid", {}).get("outcome") == "detected"
        )
        local_c2pa_detected = sum(
            1 for r in group if _local_c2pa_detected(r.get("local_c2pa"))
        )
        rows.append(
            {
                "generator": gen,
                "condition": cond,
                "images": total,
                "c2pa_detected": c2pa_detected,
                "c2pa_rate": round(c2pa_detected / total, 4) if total else None,
                "synthid_detected": synthid_detected,
                "synthid_rate": round(synthid_detected / total, 4) if total else None,
                "local_c2pa_detected": local_c2pa_detected,
                "local_c2pa_rate": round(local_c2pa_detected / total, 4)
                if total
                else None,
            }
        )

    return {
        "total": len(records),
        "rows": rows,
    }
