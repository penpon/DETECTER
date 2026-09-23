from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
import re
import shutil
import statistics
import sys
import tarfile
import tempfile
import time
import urllib.request
import warnings
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

UFD_COMMIT = "030495aea3300a8b54c0ec37ec7fe1dd7e63c619"
UFD_ARCHIVE_URL = (
    "https://github.com/WisconsinAIVision/UniversalFakeDetect/archive/"
    f"{UFD_COMMIT}.tar.gz"
)
UFD_ARCHIVE_SHA256 = "c53350bc906cf9b6b28b0e4842d4e52398d994002af0f18ba86e71d24c4957f8"
UFD_HEAD_SHA256 = "477100745713bcc957beb2b40859536859b6483fd6301b3b9293151b194c7847"
UFD_CLIP_MODEL = "ViT-L/14"
UFD_CLIP_SHA256 = "b8cca3fd41ae0c99ba7e8951adf17d267cdb84cd88be6f7c2e0eca1737a03836"
UFD_WEIGHTS_VERSION = f"{UFD_HEAD_SHA256}:{UFD_CLIP_SHA256}"
UFD_PREPROCESSING_VERSION = "ufd-rgb-exif-center224-clip-normalize-v2"
UFD_DEFAULT_THRESHOLD = 0.5
MAX_INPUT_BYTES = 50 * 1024 * 1024
MAX_IMAGE_PIXELS = 100_000_000
SUPPORTED_FORMATS = {"JPEG", "PNG", "WEBP", "HEIF"}
UFD_TILE_SIZE = 224
UFD_TILE_MAX_AXIS = 8
UFD_TILE_BATCH_SIZE = 16
PIXEL_GRID_SIZE = 32
AI_SOURCE_SUFFIXES = (
    "/trainedAlgorithmicMedia",
    "/compositeWithTrainedAlgorithmicMedia",
)
C2PA_MODEL_TYPES = {
    "c2pa.types.model",
    "c2pa.types.model.caffe",
    "c2pa.types.model.caffe2",
    "c2pa.types.model.catboost",
    "c2pa.types.model.coreml",
    "c2pa.types.model.flax",
    "c2pa.types.model.huggingface.transformers",
    "c2pa.types.model.jax",
    "c2pa.types.model.keras",
    "c2pa.types.model.lightgbm",
    "c2pa.types.model.ml_net",
    "c2pa.types.model.mxnet",
    "c2pa.types.model.onnx",
    "c2pa.types.model.openvino",
    "c2pa.types.model.openvino.parameter",
    "c2pa.types.model.openvino.topology",
    "c2pa.types.model.paddle",
    "c2pa.types.model.pytorch",
    "c2pa.types.model.sklearn",
    "c2pa.types.model.tensorflow",
    "c2pa.types.model.tensorrt",
    "c2pa.types.model.tflite",
    "c2pa.types.model.torchscript",
    "c2pa.types.model.xgboost",
}
C2PA_HUMAN_OVERSIGHT_LEVELS = {
    "fully_autonomous",
    "prompt_guided",
    "human_validated",
}
C2PA_SCIENTIFIC_DOMAIN = re.compile(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")


def default_cache_dir() -> Path:
    configured = os.environ.get("DETECTER_CACHE_DIR")
    return (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".cache" / "detecter"
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_HEIF_REGISTERED = False


def ensure_heif_opener() -> None:
    """Register the HEIF opener so HEIC/HEIF files decode via Pillow."""
    global _HEIF_REGISTERED
    if _HEIF_REGISTERED:
        return
    try:
        import pillow_heif
    except ImportError as error:
        raise ValueError(
            "HEIC/HEIF画像を読み込めません: pillow-heifが必要です"
        ) from error
    pillow_heif.register_heif_opener()
    _HEIF_REGISTERED = True


def decoded_image(path: Path) -> Image.Image:
    """Open an image for inference with EXIF orientation applied.

    The returned RGB image is owned by the caller. The input file is
    never modified; hash and C2PA checks must use the original path.
    """
    ensure_heif_opener()
    with Image.open(path) as source:
        return ImageOps.exif_transpose(source).convert("RGB")


def inspect_image(path: Path, *, max_bytes: int = MAX_INPUT_BYTES) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"画像ファイルが見つかりません: {path}")
    byte_size = path.stat().st_size
    if byte_size > max_bytes:
        raise ValueError(
            f"画像が上限 {max_bytes} bytes を超えています: {byte_size} bytes"
        )
    ensure_heif_opener()
    try:
        with Image.open(path) as image:
            image_format = image.format
            width, height = image.size
            mode = image.mode
            image.verify()
    except Exception as error:
        raise ValueError(f"画像を読み込めません: {error}") from error
    if image_format not in SUPPORTED_FORMATS:
        raise ValueError(f"未対応の画像形式です: {image_format}")
    if width * height > MAX_IMAGE_PIXELS:
        raise ValueError(f"画像の画素数が上限 {MAX_IMAGE_PIXELS} pixels を超えています")
    return {
        "format": image_format,
        "width": width,
        "height": height,
        "mode": mode,
        "bytes": byte_size,
        "sha256": file_sha256(path),
    }


def tile_bounds(
    width: int,
    height: int,
    *,
    tile_size: int = UFD_TILE_SIZE,
    max_tiles_per_axis: int = UFD_TILE_MAX_AXIS,
) -> list[tuple[int, int, int, int]]:
    """Return a deterministic, gap-free grid covering the whole image."""
    if width <= 0 or height <= 0:
        raise ValueError("画像の幅と高さは1以上にしてください")
    if tile_size <= 0 or max_tiles_per_axis <= 0:
        raise ValueError("タイル設定は1以上にしてください")
    max_tiles_per_axis = min(max_tiles_per_axis, UFD_TILE_MAX_AXIS)

    columns = min(max_tiles_per_axis, max(1, math.ceil(width / tile_size)))
    rows = min(max_tiles_per_axis, max(1, math.ceil(height / tile_size)))
    x_edges = [width * index // columns for index in range(columns + 1)]
    y_edges = [height * index // rows for index in range(rows + 1)]
    return [
        (x_edges[column], y_edges[row], x_edges[column + 1], y_edges[row + 1])
        for row in range(rows)
        for column in range(columns)
    ]


def quantized_pixel_grid(
    path: Path, *, size: int = PIXEL_GRID_SIZE
) -> list[list[list[int]]]:
    """Downsample an image with BOX averaging and quantize RGB to 0..15."""
    if size <= 0:
        raise ValueError("画素グリッドのサイズは1以上にしてください")
    with decoded_image(path) as source:
        image = source.resize((size, size), Image.Resampling.BOX)
        pixels = image.load()
        return [
            [
                [int(channel) // 16 for channel in pixels[column, row]]
                for column in range(size)
            ]
            for row in range(size)
        ]


def create_derived_jpeg(
    path: Path,
    *,
    directory: Path | None = None,
    max_bytes: int = MAX_INPUT_BYTES,
) -> Path:
    """Create the experiment's rotated, 1024px-long-side, quality-75 JPEG."""
    resolved = path.expanduser().resolve()
    inspect_image(resolved, max_bytes=max_bytes)
    with tempfile.NamedTemporaryFile(
        prefix="detecter-derived-",
        suffix=".jpg",
        dir=str(directory) if directory is not None else None,
        delete=False,
    ) as temporary:
        target = Path(temporary.name)
    try:
        with decoded_image(resolved) as image:
            long_side = max(image.size)
            if long_side != 1024:
                scale = 1024 / long_side
                image = image.resize(
                    (
                        max(1, round(image.width * scale)),
                        max(1, round(image.height * scale)),
                    ),
                    Image.Resampling.LANCZOS,
                )
            image.save(target, format="JPEG", quality=75)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target


def summarize_c2pa(c2pa_result: dict[str, Any]) -> dict[str, Any]:
    """Keep only the C2PA facts needed by the Jev experiment."""
    status = c2pa_result.get("status")
    if status == "skipped":
        status = "absent"
    if status not in {"present", "absent", "error"}:
        status = "error"

    validation_state = c2pa_result.get("validation_state")
    if "confirmation_state" in c2pa_result:
        if c2pa_result.get("confirmation_state") in {"hash_mismatch", "unverifiable"}:
            validation_state = "Invalid"
        elif c2pa_result.get("confirmed"):
            validation_state = "Trusted"
        elif (
            c2pa_result.get("signature_state") == "valid"
            and c2pa_result.get("binding_state") == "match"
        ):
            validation_state = "Valid"
        else:
            validation_state = "not_reported"
    if status != "present" or validation_state not in {"Valid", "Trusted", "Invalid"}:
        validation_state = "not_reported"
    trust_state = {
        "Trusted": "trusted",
        "Valid": "valid_untrusted",
        "Invalid": "invalid",
    }.get(validation_state, "not_reported")
    source_types = sorted(
        {
            source_type
            for source_type in c2pa_result.get("digital_source_types", [])
            if isinstance(source_type, str) and source_type.endswith(AI_SOURCE_SUFFIXES)
        }
    )
    return {
        "status": status,
        "validation_state": validation_state,
        "trust_state": trust_state,
        "ai_source_types": source_types,
        "data_hash": _data_hash_status(c2pa_result),
    }


def _ai_disclosure_records(assertions: Any) -> list[dict[str, Any]]:
    """Read C2PA 2.4 c2pa.ai-disclosure from the active manifest only."""
    records: list[dict[str, Any]] = []
    if not isinstance(assertions, list):
        return records
    for assertion in assertions:
        if not isinstance(assertion, dict):
            continue
        if assertion.get("label") != "c2pa.ai-disclosure":
            continue
        data = assertion.get("data")
        if not isinstance(data, dict):
            continue
        if set(data) - {
            "modelType",
            "modelName",
            "modelIdentifier",
            "contentProfile",
            "scientificDomain",
            "metadata",
        }:
            continue
        model_type = data.get("modelType")
        if not isinstance(model_type, str) or model_type not in C2PA_MODEL_TYPES:
            continue
        profile = data.get("contentProfile")
        if "contentProfile" in data and (
            not isinstance(profile, dict) or set(profile) - {"humanOversightLevel"}
        ):
            continue
        oversight = None
        if isinstance(profile, dict) and "humanOversightLevel" in profile:
            oversight = profile["humanOversightLevel"]
            if (
                not isinstance(oversight, str)
                or oversight not in C2PA_HUMAN_OVERSIGHT_LEVELS
            ):
                continue
        if any(
            key in data and not isinstance(data[key], str)
            for key in ("modelName", "modelIdentifier")
        ):
            continue
        domains = data.get("scientificDomain")
        if isinstance(domains, str):
            domains = [domains]
        if "scientificDomain" in data and (
            not isinstance(domains, list)
            or not domains
            or not all(
                isinstance(item, str) and C2PA_SCIENTIFIC_DOMAIN.fullmatch(item)
                for item in domains
            )
        ):
            continue
        if "metadata" in data and (
            not isinstance(data["metadata"], dict)
            or any(not isinstance(key, str) for key in data["metadata"])
        ):
            continue
        record: dict[str, Any] = {"model_type": model_type}
        if isinstance(data.get("modelName"), str):
            record["model_name"] = data["modelName"]
        if isinstance(data.get("modelIdentifier"), str):
            record["model_identifier"] = data["modelIdentifier"]
        if oversight is not None:
            record["human_oversight_level"] = oversight
        if domains:
            record["scientific_domain"] = sorted(set(domains))
        records.append(record)
    return records


def _has_ai_claim(c2pa_result: dict[str, Any]) -> bool:
    """AI usage claim from actions info or C2PA 2.4 AI disclosure."""
    return bool(
        c2pa_result.get("ai_source_assertion")
        or c2pa_result.get("ai_disclosure_assertion")
    )


def _data_hash_status(c2pa_result: dict[str, Any]) -> str:
    state = _c2pa_verification(c2pa_result.get("validation_results"))["binding_state"]
    return state if state in {"match", "mismatch"} else "not_reported"


def _c2pa_verification(
    results: Any, *, explicit_anchors: bool = False
) -> dict[str, Any]:
    # Only the active manifest binds this file; ingredient results describe other files.
    active = results.get("activeManifest", {}) if isinstance(results, dict) else {}
    if not isinstance(active, dict):
        active = {}
    codes: dict[str, set[str]] = {}
    malformed = False
    for bucket in ("success", "failure", "informational"):
        entries = active.get(bucket, [])
        codes[bucket] = set()
        if not isinstance(entries, list):
            malformed = True
            continue
        for item in entries:
            if isinstance(item, dict) and isinstance(item.get("code"), str):
                codes[bucket].add(item["code"])
            else:
                malformed = True
    success = codes.get("success", set())
    reported = set().union(*codes.values())
    signature = "unknown"
    if "claimSignature.validated" in success:
        signature = "valid"
    if reported & {"claimSignature.mismatch", "claimSignature.missing"}:
        signature = "invalid"
    trust = "not_checked" if not explicit_anchors else "unknown"
    if explicit_anchors and "signingCredential.trusted" in success:
        trust = "trusted"
    trust_failures = {
        "signingCredential.untrusted",
        "signingCredential.invalid",
        "signingCredential.expired",
        "signingCredential.revoked",
    }
    if reported & trust_failures:
        trust = "untrusted"
    binding = "unknown"
    hash_types = ("dataHash", "bmffHash", "boxesHash")
    if success & {f"assertion.{kind}.match" for kind in hash_types}:
        binding = "match"
    if reported & {f"assertion.{kind}.mismatch" for kind in hash_types}:
        binding = "mismatch"
    reasons = []
    if signature != "valid":
        reasons.append(f"signature_{signature}")
    if trust != "trusted":
        reasons.append(f"signer_{trust}")
    if binding != "match":
        reasons.append(
            "asset_hash_mismatch" if binding == "mismatch" else "asset_binding_unknown"
        )
    if codes.get("failure"):
        reasons.append("validation_failed")
    if malformed:
        reasons.append("invalid_validation_results")
    if binding == "mismatch":
        state = "hash_mismatch"
    elif (
        malformed
        or signature != "valid"
        or (codes.get("failure", set()) - trust_failures)
    ):
        state = "unverifiable"
    elif binding == "unknown":
        state = "binding_unknown"
    elif trust == "untrusted":
        state = "untrusted"
    elif trust == "trusted":
        state = "trusted"
    else:
        state = "cryptographically_valid"
    return {
        "signature_state": signature,
        "trust_state": trust,
        "binding_state": binding,
        "confirmation_state": state,
        "confirmed": state == "trusted",
        "reasons": reasons,
    }


def _unavailable_c2pa(status: str) -> dict[str, Any]:
    state = {"skipped": "not_checked", "absent": "absent", "error": "unverifiable"}[
        status
    ]
    return {
        "status": status,
        "manifest_present": False,
        "signature_state": "not_checked" if status == "skipped" else "unknown",
        "trust_state": "not_checked",
        "binding_state": "not_checked" if status == "skipped" else "unknown",
        "generation_scope": "unknown",
        "confirmation_state": state,
        "confirmed": False,
        "cryptographically_valid": False,
        "trusted": False,
        "reasons": [f"c2pa_{state}"],
    }


def inspect_c2pa(
    path: Path, *, trust_anchors: Path | None = None, check: bool = True
) -> dict[str, Any]:
    """Read embedded C2PA data without fetching remote manifests or OCSP."""
    if not check:
        return _unavailable_c2pa("skipped")
    try:
        import c2pa

        settings_data: dict[str, Any] = {
            "verify": {
                "verify_after_reading": True,
                "remote_manifest_fetch": False,
                "ocsp_fetch": False,
                "verify_cert_anchors": trust_anchors is not None,
            }
        }
        settings = None
        if trust_anchors is not None:
            anchors = trust_anchors.expanduser().read_text(encoding="utf-8")
            settings_data["verify"]["verify_cert_anchors"] = True
            settings_data["trust"] = {"trust_anchors": anchors}
            settings = c2pa.Settings.from_dict(settings_data)
            context = c2pa.Context(settings)
        else:
            context = c2pa.Context.from_dict(settings_data)
        try:
            reader = c2pa.Reader.try_create(path, context=context)
            if reader is None:
                return _unavailable_c2pa("absent")
            try:
                store = json.loads(reader.json())
                if not isinstance(store, dict):
                    raise TypeError(
                        "C2PAのマニフェストストアがオブジェクトではありません"
                    )
                active = reader.get_active_manifest() or {}
                if not isinstance(active, dict):
                    raise TypeError(
                        "C2PAの有効マニフェストがオブジェクトではありません"
                    )
                validation_state = reader.get_validation_state()
                validation_results = reader.get_validation_results()
            finally:
                reader.close()
        finally:
            context.close()
            if settings is not None:
                settings.close()
    # c2pa-python can surface native-library, parse, filesystem, and settings errors.
    except Exception as error:  # noqa: BLE001
        return {
            **_unavailable_c2pa("error"),
            "error": f"{type(error).__name__}: {error}",
        }

    # Do not promote ingredient history or arbitrary nested metadata to an asset claim.
    action_records = []
    assertions = active.get("assertions", [])
    for assertion in assertions if isinstance(assertions, list) else []:
        if not isinstance(assertion, dict):
            continue
        label = assertion.get("label", "")
        data = assertion.get("data")
        if (
            not isinstance(label, str)
            or label not in {"c2pa.actions", "c2pa.actions.v2"}
            or not isinstance(data, dict)
        ):
            continue
        entries = data.get("actions", [])
        if isinstance(entries, list):
            action_records.extend(entry for entry in entries if isinstance(entry, dict))
    source_types = sorted(
        {
            entry["digitalSourceType"]
            for entry in action_records
            if isinstance(entry.get("digitalSourceType"), str)
        }
    )
    actions = sorted(
        {
            entry["action"]
            for entry in action_records
            if isinstance(entry.get("action"), str)
        }
    )
    generation_scope = "unknown"
    for entry in action_records:
        source = entry.get("digitalSourceType", "")
        if not isinstance(source, str):
            continue
        if source.endswith("/compositeWithTrainedAlgorithmicMedia") or (
            entry.get("action") == "c2pa.edited"
            and source.endswith("/trainedAlgorithmicMedia")
        ):
            generation_scope = "partial"
            break
        if entry.get("action") == "c2pa.created" and source.endswith(
            "/trainedAlgorithmicMedia"
        ):
            generation_scope = "full"
    ai_source_assertion = any(
        source_type.endswith(AI_SOURCE_SUFFIXES) for source_type in source_types
    )
    ai_disclosure = _ai_disclosure_records(active.get("assertions", []))
    signature_info = active.get("signature_info")
    if not isinstance(signature_info, dict):
        signature_info = {}
    verification = _c2pa_verification(
        validation_results, explicit_anchors=trust_anchors is not None
    )
    if validation_state == "Invalid":
        verification["confirmed"] = False
        if verification["confirmation_state"] not in {"hash_mismatch", "untrusted"}:
            verification["confirmation_state"] = "unverifiable"
        if "validation_failed" not in verification["reasons"]:
            verification["reasons"].append("validation_failed")
    return {
        "status": "present",
        "manifest_present": True,
        "active_manifest": store.get("active_manifest"),
        "claim_generator": active.get("claim_generator"),
        "issuer": signature_info.get("issuer"),
        "validation_state": validation_state,
        "cryptographically_valid": verification["signature_state"] == "valid",
        "trusted": verification["trust_state"] == "trusted",
        **verification,
        "validation_results": validation_results,
        "actions": actions,
        "digital_source_types": source_types,
        "ai_source_assertion": ai_source_assertion,
        "ai_disclosure": ai_disclosure,
        "ai_disclosure_assertion": bool(ai_disclosure),
        "generation_scope": generation_scope,
    }


def _download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        with (
            urllib.request.urlopen(url, timeout=120) as source,
            temporary.open("wb") as output,
        ):
            shutil.copyfileobj(source, output)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _safe_extract(archive: Path, destination: Path) -> None:
    destination_root = destination.resolve()
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            target = (destination / member.name).resolve()
            if (
                not target.is_relative_to(destination_root)
                or member.issym()
                or member.islnk()
            ):
                raise RuntimeError(f"安全でないアーカイブ項目です: {member.name}")
        bundle.extractall(destination)


def ensure_ufd_source(cache_dir: Path) -> Path:
    cache_dir = cache_dir.expanduser().resolve()
    source_dir = cache_dir / f"UniversalFakeDetect-{UFD_COMMIT}"
    head_path = source_dir / "pretrained_weights" / "fc_weights.pth"
    if head_path.is_file() and file_sha256(head_path) == UFD_HEAD_SHA256:
        return source_dir

    archive = cache_dir / f"UniversalFakeDetect-{UFD_COMMIT}.tar.gz"
    if not archive.is_file() or file_sha256(archive) != UFD_ARCHIVE_SHA256:
        _download(UFD_ARCHIVE_URL, archive)
    if file_sha256(archive) != UFD_ARCHIVE_SHA256:
        raise RuntimeError("UniversalFakeDetectのアーカイブ検証に失敗しました")

    cache_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ufd-", dir=cache_dir) as temporary:
        extracted = Path(temporary)
        _safe_extract(archive, extracted)
        candidates = [path for path in extracted.iterdir() if path.is_dir()]
        if len(candidates) != 1:
            raise RuntimeError("UniversalFakeDetectのアーカイブ構造を確認できません")
        if source_dir.exists():
            shutil.rmtree(source_dir)
        candidates[0].replace(source_dir)
    if not head_path.is_file() or file_sha256(head_path) != UFD_HEAD_SHA256:
        raise RuntimeError("UniversalFakeDetectの判定層を検証できません")
    return source_dir


class UfdDetector:
    def __init__(self, *, cache_dir: Path | None = None, device: str = "auto") -> None:
        import torch
        from torchvision import transforms

        self.torch = torch
        self.cache_dir = (cache_dir or default_cache_dir()).expanduser().resolve()
        self.source_dir = ensure_ufd_source(self.cache_dir)
        if str(self.source_dir) not in sys.path:
            sys.path.insert(0, str(self.source_dir))
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="pkg_resources is deprecated as an API.*",
                category=UserWarning,
            )
            clip_module = importlib.import_module("models.clip.clip")

        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDAを利用できません")
        self.device = torch.device(device)
        self.backbone, _ = clip_module.load(
            UFD_CLIP_MODEL,
            device="cpu",
            download_root=str(self.cache_dir / "clip"),
        )
        self.head = torch.nn.Linear(768, 1)
        state = torch.load(
            self.source_dir / "pretrained_weights" / "fc_weights.pth",
            map_location="cpu",
            weights_only=True,
        )
        self.head.load_state_dict(state)
        self.backbone.eval().to(self.device)
        self.head.eval().to(self.device)
        self.transform = transforms.Compose(
            [
                transforms.CenterCrop(224),
                transforms.ToTensor(),
                transforms.Normalize(
                    (0.48145466, 0.4578275, 0.40821073),
                    (0.26862954, 0.26130258, 0.27577711),
                ),
            ]
        )

    def score_images(self, images: Sequence[Image.Image]) -> list[float]:
        tensors = self.torch.stack(
            [self.transform(image.convert("RGB")) for image in images]
        ).to(self.device)
        with self.torch.inference_mode():
            features = self.backbone.encode_image(tensors)
            scores = self.head(features).sigmoid().flatten().tolist()
        return [float(score) for score in scores]

    def score_image(self, image: Image.Image) -> float:
        return self.score_images([image])[0]

    def score(self, path: Path) -> float:
        with decoded_image(path) as image:
            return self.score_image(image)

    def metadata(self) -> dict[str, Any]:
        return {
            "model": "ufd",
            "model_version": UFD_COMMIT,
            "weights_version": UFD_WEIGHTS_VERSION,
            "preprocessing_version": UFD_PREPROCESSING_VERSION,
            "name": "UniversalFakeDetect",
            "source_commit": UFD_COMMIT,
            "clip_model": UFD_CLIP_MODEL,
            "device": str(self.device),
        }


def _score_tile_batch(
    detector: Any,
    images: Sequence[Image.Image],
) -> list[float]:
    score_images = getattr(detector, "score_images", None)
    if callable(score_images):
        return [float(score) for score in score_images(images)]

    score_image = getattr(detector, "score_image", None)
    if callable(score_image):
        return [float(score_image(image)) for image in images]

    score = getattr(detector, "score", None)
    if not callable(score):
        raise TypeError("UFD検知器にスコア関数がありません")
    with tempfile.TemporaryDirectory(prefix="detecter-tiles-") as temporary:
        paths: list[Path] = []
        for index, image in enumerate(images):
            path = Path(temporary) / f"tile-{index}.png"
            image.save(path, format="PNG")
            paths.append(path)
        return [float(score(path)) for path in paths]


def analyze_full_area_tiles(
    path: Path,
    detector: Any,
    *,
    threshold: float = UFD_DEFAULT_THRESHOLD,
    max_bytes: int = MAX_INPUT_BYTES,
    tile_size: int = UFD_TILE_SIZE,
    max_tiles_per_axis: int = UFD_TILE_MAX_AXIS,
    batch_size: int = UFD_TILE_BATCH_SIZE,
) -> dict[str, Any]:
    """Run the unchanged UFD detector over a gap-free full-image tile grid."""
    if batch_size <= 0:
        raise ValueError("タイルのバッチサイズは1以上にしてください")
    max_tiles_per_axis = min(max_tiles_per_axis, UFD_TILE_MAX_AXIS)
    batch_size = min(batch_size, UFD_TILE_BATCH_SIZE)
    resolved = path.expanduser().resolve()
    inspect_image(resolved, max_bytes=max_bytes)
    bounds: list[tuple[int, int, int, int]] = []
    rows = columns = 0
    try:
        with decoded_image(resolved) as image:
            bounds = tile_bounds(
                image.width,
                image.height,
                tile_size=tile_size,
                max_tiles_per_axis=max_tiles_per_axis,
            )
            columns = min(
                max_tiles_per_axis, max(1, math.ceil(image.width / tile_size))
            )
            rows = min(max_tiles_per_axis, max(1, math.ceil(image.height / tile_size)))
            scores: list[float] = []
            for start in range(0, len(bounds), batch_size):
                batch_bounds = bounds[start : start + batch_size]
                batch = [
                    image.crop(box).resize(
                        (UFD_TILE_SIZE, UFD_TILE_SIZE), Image.Resampling.LANCZOS
                    )
                    for box in batch_bounds
                ]
                scores.extend(_score_tile_batch(detector, batch))
    except Exception as error:  # noqa: BLE001
        return {
            "status": "error",
            "tile_count": len(bounds),
            "rows": rows,
            "columns": columns,
            "error_type": type(error).__name__,
        }

    if len(scores) != len(bounds):
        return {
            "status": "error",
            "tile_count": len(bounds),
            "rows": rows,
            "columns": columns,
            "error_type": "DetectorResultLengthError",
        }
    tiles = [
        {
            "index": index,
            "row": index // columns,
            "column": index % columns,
            "bounds": list(box),
            "raw_score": score,
            "predicted_ai": score >= threshold,
        }
        for index, (box, score) in enumerate(zip(bounds, scores, strict=True))
    ]
    return {
        "status": "ok",
        "rows": rows,
        "columns": columns,
        "tile_count": len(tiles),
        "tile_size": UFD_TILE_SIZE,
        "threshold": threshold,
        "mean": statistics.fmean(scores),
        "median": statistics.median(scores),
        "min": min(scores),
        "max": max(scores),
        "stddev": statistics.pstdev(scores),
        "above_threshold_count": sum(score >= threshold for score in scores),
        "tiles": tiles,
    }


def build_jev_state(
    media: dict[str, Any],
    c2pa_result: dict[str, Any],
    tile_result: dict[str, Any],
    *,
    input_variant: str,
) -> dict[str, Any]:
    """Build the text-only state without file identity or local verdict fields."""
    return {
        "image": {
            "variant": input_variant,
            "format": media.get("format"),
            "width": media.get("width"),
            "height": media.get("height"),
            "mode": media.get("mode"),
        },
        "c2pa": summarize_c2pa(c2pa_result),
        "universal_fake_detect": tile_result,
        "limitations": [
            "Jev receives text-only state; no image bytes or base64 are sent.",
            "UniversalFakeDetect scores are uncalibrated detector scores, not probabilities of correctness.",
            "All tile scores use the same UniversalFakeDetect detector.",
            "SynthID was not checked.",
            "No detected signal is not proof that the image is a real photograph.",
        ],
    }


def provisional_verdict(
    c2pa_result: dict[str, Any], ufd_result: dict[str, Any]
) -> dict[str, Any]:
    if c2pa_result.get("status") == "present" and (
        c2pa_result.get("validation_state") == "Invalid"
        or c2pa_result.get("confirmation_state")
        in {"hash_mismatch", "binding_unknown", "unverifiable"}
    ):
        return {
            "state": "inconclusive",
            "reason": "C2PAマニフェストの署名またはデータ完全性を検証できませんでした",
            "experimental": True,
        }
    if (
        c2pa_result.get("status") == "present"
        and c2pa_result.get("confirmed")
        and _has_ai_claim(c2pa_result)
    ):
        classifier_disagrees = ufd_result.get("status") == "ok" and not ufd_result.get(
            "predicted_ai"
        )
        if c2pa_result.get("generation_scope") == "partial":
            reason = (
                "信頼済みC2PAにAIによる部分編集の記録があります。"
                "全体生成の根拠ではありません"
            )
        else:
            reason = "信頼済みC2PAにAI生成・編集の主張があります"
        if classifier_disagrees:
            reason += "。分類器スコアは暫定しきい値未満のため、根拠の食い違いを確認してください"
        return {
            "state": "ai_evidence_confirmed",
            "reason": reason,
            "generation_scope": c2pa_result.get("generation_scope", "unknown"),
            "evidence_conflict": classifier_disagrees,
            "experimental": True,
        }
    if c2pa_result.get("status") == "present" and _has_ai_claim(c2pa_result):
        return {
            "state": "ai_likely",
            "reason": "C2PAにAI生成・編集の主張がありますが、署名者は信頼済みではありません",
            "experimental": True,
        }
    if ufd_result.get("status") == "ok" and ufd_result.get("predicted_ai"):
        return {
            "state": "ai_likely",
            "reason": "UniversalFakeDetectの未調整スコアが暫定しきい値以上です",
            "experimental": True,
        }
    if c2pa_result.get("status") == "error" or ufd_result.get("status") != "ok":
        return {
            "state": "inconclusive",
            "reason": "必要な検査の一部を完了できませんでした",
            "experimental": True,
        }
    return {
        "state": "no_ai_signal_detected",
        "reason": "今回の検査ではAIを示す信号を確認できませんでした",
        "experimental": True,
    }


def analyze_image(
    path: Path,
    *,
    detector: UfdDetector | None,
    threshold: float = UFD_DEFAULT_THRESHOLD,
    check_c2pa: bool = True,
    c2pa_trust_anchors: Path | None = None,
    max_bytes: int = MAX_INPUT_BYTES,
) -> dict[str, Any]:
    started = time.perf_counter()
    resolved = path.expanduser().resolve()
    media = inspect_image(resolved, max_bytes=max_bytes)
    c2pa_result = inspect_c2pa(
        resolved, trust_anchors=c2pa_trust_anchors, check=check_c2pa
    )
    if detector is None:
        ufd_result: dict[str, Any] = {"status": "skipped"}
    else:
        try:
            raw_score = detector.score(resolved)
            ufd_result = {
                "status": "ok",
                **detector.metadata(),
                "raw_score": raw_score,
                "threshold": threshold,
                "threshold_source": "upstream_default_not_calibrated",
                "predicted_ai": raw_score >= threshold,
            }
        # Preserve C2PA and media data even when one detector input fails.
        except Exception as error:  # noqa: BLE001
            ufd_result = {
                "status": "error",
                **detector.metadata(),
                "error": f"{type(error).__name__}: {error}",
            }
    return {
        "schema_version": 1,
        "analyzed_at": datetime.now(UTC).isoformat(),
        "path": str(resolved),
        "media": media,
        "c2pa": c2pa_result,
        "universal_fake_detect": ufd_result,
        "verdict": provisional_verdict(c2pa_result, ufd_result),
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
    }
