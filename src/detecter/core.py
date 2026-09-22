from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.request
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image

UFD_COMMIT = "030495aea3300a8b54c0ec37ec7fe1dd7e63c619"
UFD_ARCHIVE_URL = (
    "https://github.com/WisconsinAIVision/UniversalFakeDetect/archive/"
    f"{UFD_COMMIT}.tar.gz"
)
UFD_ARCHIVE_SHA256 = "c53350bc906cf9b6b28b0e4842d4e52398d994002af0f18ba86e71d24c4957f8"
UFD_HEAD_SHA256 = "477100745713bcc957beb2b40859536859b6483fd6301b3b9293151b194c7847"
UFD_CLIP_MODEL = "ViT-L/14"
UFD_DEFAULT_THRESHOLD = 0.5
MAX_INPUT_BYTES = 50 * 1024 * 1024
MAX_IMAGE_PIXELS = 100_000_000
SUPPORTED_FORMATS = {"JPEG", "PNG", "WEBP"}
AI_SOURCE_SUFFIXES = (
    "/trainedAlgorithmicMedia",
    "/compositeWithTrainedAlgorithmicMedia",
)


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


def inspect_image(path: Path, *, max_bytes: int = MAX_INPUT_BYTES) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"画像ファイルが見つかりません: {path}")
    byte_size = path.stat().st_size
    if byte_size > max_bytes:
        raise ValueError(
            f"画像が上限 {max_bytes} bytes を超えています: {byte_size} bytes"
        )
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


def _walk_values(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key, child
            yield from _walk_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_values(child)


def inspect_c2pa(path: Path, *, trust_anchors: Path | None = None) -> dict[str, Any]:
    """Read embedded C2PA data without fetching remote manifests or OCSP."""
    try:
        import c2pa

        settings_data: dict[str, Any] = {
            "verify": {
                "verify_after_reading": True,
                "remote_manifest_fetch": False,
                "ocsp_fetch": False,
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
                return {"status": "absent", "manifest_present": False}
            try:
                store = json.loads(reader.json())
                active = reader.get_active_manifest() or {}
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
            "status": "error",
            "manifest_present": False,
            "error": f"{type(error).__name__}: {error}",
        }

    source_types = sorted(
        {
            value
            for key, value in _walk_values(active)
            if key in {"digitalSourceType", "digital_source_type"}
            and isinstance(value, str)
        }
    )
    actions = sorted(
        {
            value
            for key, value in _walk_values(active)
            if key == "action" and isinstance(value, str)
        }
    )
    ai_source_assertion = any(
        source_type.endswith(AI_SOURCE_SUFFIXES) for source_type in source_types
    )
    signature_info = active.get("signature_info") or {}
    return {
        "status": "present",
        "manifest_present": True,
        "active_manifest": store.get("active_manifest"),
        "claim_generator": active.get("claim_generator"),
        "issuer": signature_info.get("issuer"),
        "validation_state": validation_state,
        "cryptographically_valid": validation_state in {"Valid", "Trusted"},
        "trusted": validation_state == "Trusted",
        "validation_results": validation_results,
        "actions": actions,
        "digital_source_types": source_types,
        "ai_source_assertion": ai_source_assertion,
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

    def score(self, path: Path) -> float:
        with Image.open(path) as image:
            tensor = self.transform(image.convert("RGB")).unsqueeze(0).to(self.device)
        with self.torch.inference_mode():
            features = self.backbone.encode_image(tensor)
            score = self.head(features).sigmoid().item()
        return float(score)

    def metadata(self) -> dict[str, Any]:
        return {
            "name": "UniversalFakeDetect",
            "source_commit": UFD_COMMIT,
            "clip_model": UFD_CLIP_MODEL,
            "device": str(self.device),
        }


def provisional_verdict(
    c2pa_result: dict[str, Any], ufd_result: dict[str, Any]
) -> dict[str, Any]:
    if (
        c2pa_result.get("status") == "present"
        and c2pa_result.get("validation_state") == "Invalid"
    ):
        return {
            "state": "inconclusive",
            "reason": "C2PAマニフェストの署名またはデータ完全性を検証できませんでした",
            "experimental": True,
        }
    if (
        c2pa_result.get("status") == "present"
        and c2pa_result.get("trusted")
        and c2pa_result.get("ai_source_assertion")
    ):
        return {
            "state": "ai_evidence_confirmed",
            "reason": "信頼済みC2PAにAI生成・編集の出典種別があります",
            "experimental": True,
        }
    if c2pa_result.get("status") == "present" and c2pa_result.get(
        "ai_source_assertion"
    ):
        return {
            "state": "ai_likely",
            "reason": "C2PAにAI生成・編集の出典種別がありますが、署名者は信頼済みではありません",
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
    c2pa_result = (
        inspect_c2pa(resolved, trust_anchors=c2pa_trust_anchors)
        if check_c2pa
        else {"status": "skipped"}
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
