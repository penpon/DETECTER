"""Pinned Community Forensics 384 inference; scores are uncalibrated logits."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import platform
from pathlib import Path
from typing import Any

from PIL import Image

from .core import (
    _download,
    default_cache_dir,
    ensure_heif_opener,
    file_sha256,
    inspect_image,
)

MODEL = "community-forensics-384"
SOURCE_COMMIT = "ee5b71d43db0f3779e1edd64ee927b13f2dd6ad4"
WEIGHTS_REVISION = "6076002bf0d9dd37537f965ee2f06f826c333b61"
WEIGHTS_SHA256 = "b89f36275f3bf5e2b040eee36597a8f19db051bff9a473a9cf7b2466284fb387"
WEIGHTS_URL = (
    "https://huggingface.co/OwensLab/commfor-model-384/resolve/"
    f"{WEIGHTS_REVISION}/model.safetensors"
)
ARCHITECTURE = "vit_small_patch16_384.augreg_in21k_ft_in1k"
PREPROCESSING = {
    "color_mode": "RGB",
    "resize_short_edge": 440,
    "interpolation": "bilinear",
    "antialias": True,
    "center_crop": 384,
    "mean": [0.485, 0.456, 0.406],
    "std": [0.229, 0.224, 0.225],
    "dtype": "float32",
    "exif_transpose": False,
}
PREPROCESSING_VERSION = f"{SOURCE_COMMIT}:test-384-rgb-v1"


def preprocess(image: Image.Image) -> Any:
    from torchvision import transforms

    return transforms.Compose(
        [
            transforms.Resize(
                440, interpolation=transforms.InterpolationMode.BILINEAR, antialias=True
            ),
            transforms.CenterCrop(384),
            transforms.ToTensor(),
            transforms.Normalize(PREPROCESSING["mean"], PREPROCESSING["std"]),
        ]
    )(image.convert("RGB"))


def weights_path(cache_dir: Path | None = None) -> Path:
    path = (
        (cache_dir or default_cache_dir())
        / MODEL
        / WEIGHTS_REVISION
        / "model.safetensors"
    )
    if not path.is_file():
        _download(WEIGHTS_URL, path)
    if file_sha256(path) != WEIGHTS_SHA256:
        raise ValueError(
            f"重みのSHA-256が一致しません。キャッシュを確認してください: {path}"
        )
    return path


def load_model(cache_dir: Path | None = None) -> Any:
    try:
        import timm
        from safetensors.torch import load_file
    except ImportError as error:
        raise RuntimeError(
            "uv sync --extra community-forensics を実行してください"
        ) from error

    state = load_file(str(weights_path(cache_dir)), device="cpu")
    model = timm.create_model(ARCHITECTURE, pretrained=False, num_classes=1)
    # The official ViTClassifier wraps this same timm model under `vit`.
    model.load_state_dict(
        {name.removeprefix("vit."): value for name, value in state.items()}, strict=True
    )
    return model.eval()


def infer(path: Path, *, cache_dir: Path | None = None, model: Any = None) -> float:
    import torch

    if model is None:
        model = load_model(cache_dir)
    ensure_heif_opener()
    with Image.open(path) as image:
        tensor = preprocess(image).unsqueeze(0)
    with torch.inference_mode():
        return float(model(tensor).item())


def measure(
    path: Path,
    *,
    image_id: str | None = None,
    device: str = "cpu",
    cache_dir: Path | None = None,
    expected_sha256: str | None = None,
    model: Any = None,
    model_error: Exception | None = None,
) -> dict[str, Any]:
    path = Path(path).expanduser()
    libraries = {}
    for name in ("torch", "torchvision", "Pillow", "timm", "safetensors"):
        try:
            libraries[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            libraries[name] = None
    record: dict[str, Any] = {
        "schema_version": 1,
        "image_id": image_id or str(path),
        "sha256": expected_sha256,
        "model": MODEL,
        "model_version": SOURCE_COMMIT,
        "weights_version": f"{WEIGHTS_REVISION}:sha256:{WEIGHTS_SHA256}",
        "preprocessing_version": PREPROCESSING_VERSION,
        "preprocessing": dict(PREPROCESSING),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "device": device,
            "libraries": libraries,
        },
        "status": "error",
        "raw_score": None,
        "error": None,
    }
    try:
        actual_hash = file_sha256(path)
        record["observed_sha256"] = actual_hash
        if expected_sha256 is not None and actual_hash != expected_sha256:
            raise ValueError("image hash mismatch")
        record["sha256"] = actual_hash
        inspect_image(path)
        if device != "cpu":
            raise ValueError("Community Forensicsの実行機器はcpuを指定してください")
        if model_error is not None:
            raise model_error
        score = infer(path, cache_dir=cache_dir, model=model)
        if not math.isfinite(score):
            raise ValueError("モデルが有限数値ではないスコアを返しました")
        record.update(status="ok", raw_score=score)
    except Exception as error:  # noqa: BLE001 - every failed image needs a record
        record["error"] = f"{type(error).__name__}: {error}"
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Community Forensics 384 (MIT) CPU計測。スコアは確率ではありません。"
    )
    parser.add_argument("image", type=Path)
    parser.add_argument("--image-id")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--output", default="-")
    args = parser.parse_args(argv)
    record = measure(
        args.image, image_id=args.image_id, device=args.device, cache_dir=args.cache_dir
    )
    payload = json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n"
    if args.output == "-":
        print(payload, end="")
    else:
        Path(args.output).write_text(payload, encoding="utf-8")
    return 0 if record["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
