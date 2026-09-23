"""Pinned CuRe inference; scores are uncalibrated fake probabilities."""

from __future__ import annotations

import argparse
import importlib.metadata
import io
import json
import math
import platform
from collections import OrderedDict
from pathlib import Path
from typing import Any

import torch
from PIL import Image
from torch import nn
from torch.nn import functional as F

from .core import _download, default_cache_dir, file_sha256, inspect_image

MODEL = "cure"
SOURCE_COMMIT = "8f7832c83dcd3f4f89de955103e94a64ddc3cdc9"
ADAPTER_SHA256 = "17cabb334563c15abc8827db87dc272a4aef10f4279025faee1ef8d32c444ae1"
ADAPTER_URL = (
    "https://raw.githubusercontent.com/manic-cui/CuRe/"
    f"{SOURCE_COMMIT}/weights/cure_adapter.pt"
)
BASE_REPO_ID = "facebook/PE-Core-L14-336"
BASE_FILENAME = "PE-Core-L14-336.pt"
BASE_REVISION = "bafb0f76541d399057e980a25947f67acec76575"
BASE_SHA256 = "0cdab5b338cbaa1e7a5dcd1b2fb4c9f4d5df1abd289564658edbab64a650e7e8"
ARCHITECTURE = "pe-core-l14-336 visual tower + qv-lora-r64 + subspace-128 + linear-2"
PREPROCESSING = {
    "color_mode": "RGB",
    "png_recompress": {"format": "JPEG", "quality": 96},
    "smallest_max_size": 390,
    "center_crop": 390,
    "resize": [336, 336],
    "interpolation": "bicubic",
    "jpeg_recompress_quality": 70,
    "mean": [0.5, 0.5, 0.5],
    "std": [0.5, 0.5, 0.5],
    "dtype": "float32",
    "exif_transpose": False,
}
PREPROCESSING_VERSION = f"{SOURCE_COMMIT}:cure-336-rgb-v1"


# The vision backbone below is adapted from Perception Encoder by Meta
# Platforms, Inc. and affiliates (Apache-2.0), reduced to the fixed-resolution
# visual feature path used by CuRe. See THIRD_PARTY.md and the upstream NOTICE.
class Rotary2D(nn.Module):
    def __init__(self):
        super().__init__()
        frequencies = 1.0 / (10000 ** (torch.arange(0, 32, 2).float() / 32))
        positions = torch.arange(24).to(frequencies.dtype) + 1
        axis = torch.einsum("..., f -> ... f", positions, frequencies)
        axis = axis.repeat_interleave(2, dim=-1)
        vertical = axis[:, None].expand(24, 24, -1)
        horizontal = axis[None, :].expand(24, 24, -1)
        angles = torch.cat([horizontal, vertical], dim=-1).reshape(576, 64)
        angles = torch.cat([torch.zeros(1, 64), angles], dim=0)
        self.register_buffer("angles", angles[None, None], persistent=False)

    @torch.amp.autocast("cuda", enabled=False)
    def forward(self, values):
        first, second = values.reshape(*values.shape[:-1], -1, 2).unbind(-1)
        rotated = torch.stack([-second, first], dim=-1).flatten(-2)
        result = values * self.angles.cos() + rotated * self.angles.sin()
        return result.contiguous().to(values.dtype)


class Attention(nn.Module):
    def __init__(self, rope):
        super().__init__()
        self.in_proj_weight = nn.Parameter(torch.empty(3072, 1024))
        self.in_proj_bias = nn.Parameter(torch.empty(3072))
        self.out_proj = nn.Linear(1024, 1024)
        self.lora_A_q = nn.Parameter(torch.empty(64, 1024))
        self.lora_B_q = nn.Parameter(torch.empty(1024, 64))
        self.lora_A_v = nn.Parameter(torch.empty(64, 1024))
        self.lora_B_v = nn.Parameter(torch.empty(1024, 64))
        self.rope = rope

    def forward(self, x):
        batch, sequence, width = x.shape
        projection = F.linear(x, self.in_proj_weight, self.in_proj_bias)
        projection = (
            projection.unflatten(-1, (3, width))
            .unsqueeze(0)
            .transpose(0, -2)
            .squeeze(-2)
            .contiguous()
        )
        query, key, value = projection[0], projection[1], projection[2]
        query = query + 2.0 * F.linear(F.linear(x, self.lora_A_q), self.lora_B_q)
        value = value + 2.0 * F.linear(F.linear(x, self.lora_A_v), self.lora_B_v)
        query = query.reshape(batch, sequence, 16, 64).transpose(1, 2)
        key = key.reshape(batch, sequence, 16, 64).transpose(1, 2)
        value = value.reshape(batch, sequence, 16, 64).transpose(1, 2)
        query, key = self.rope(query), self.rope(key)
        attended = F.scaled_dot_product_attention(
            query,
            key,
            value,
            attn_mask=None,
            dropout_p=0.0,
            is_causal=False,
            scale=64**-0.5,
        )
        attended = attended.transpose(1, 2).reshape(batch, sequence, width)
        return F.linear(attended, self.out_proj.weight, self.out_proj.bias)


class ResidualBlock(nn.Module):
    def __init__(self, rope):
        super().__init__()
        self.attn = Attention(rope)
        self.ln_1 = nn.LayerNorm(1024, eps=1e-5)
        self.ln_2 = nn.LayerNorm(1024, eps=1e-5)
        self.mlp = nn.Sequential(
            OrderedDict(
                [
                    ("c_fc", nn.Linear(1024, 4096)),
                    ("gelu", nn.GELU()),
                    ("c_proj", nn.Linear(4096, 1024)),
                ]
            )
        )

    def forward(self, x):
        x = x + self.attn(self.ln_1(x))
        return x + self.mlp(self.ln_2(x))


class Transformer(nn.Module):
    def __init__(self, rope):
        super().__init__()
        self.resblocks = nn.ModuleList([ResidualBlock(rope) for _ in range(24)])

    def forward(self, x):
        for block in self.resblocks:
            x = block(x)
        return x


class PECore(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv1 = nn.Conv2d(3, 1024, kernel_size=14, stride=14, bias=False)
        self.class_embedding = nn.Parameter(torch.empty(1024))
        self.positional_embedding = nn.Parameter(torch.empty(577, 1024))
        self.ln_pre = nn.LayerNorm(1024, eps=1e-5)
        self.ln_post = nn.LayerNorm(1024, eps=1e-5)
        self.transformer = Transformer(Rotary2D())

    def forward(self, images):
        if images.ndim != 4 or tuple(images.shape[1:]) != (3, 336, 336):
            raise ValueError("Expected image tensors with shape [N, 3, 336, 336]")
        batch = images.shape[0]
        x = self.conv1(images).permute(0, 2, 3, 1).reshape(batch, 576, 1024)
        cls = self.class_embedding.view(1, 1, -1).expand(batch, -1, -1)
        x = torch.cat([cls, x], dim=1)
        x = x + self.positional_embedding[None]
        x = self.transformer(self.ln_pre(x))
        return self.ln_post(x)[:, 1:].mean(dim=1).float()


class CuRe(nn.Module):
    def __init__(self):
        super().__init__()
        self.backbone = PECore()
        self.register_buffer("mu", torch.empty(1024))
        # Preserve the checkpoint's column-major projection layout.
        self.register_buffer("W", torch.empty(128, 1024).t())
        self.head = nn.Linear(128, 2)

    @torch.inference_mode()
    def forward(self, images):
        with torch.amp.autocast("cuda", enabled=images.is_cuda):
            features = self.backbone(images)
        return self.head((features - self.mu) @ self.W)


def preprocess(image: Image.Image) -> Any:
    try:
        import albumentations as A
        import cv2
        import numpy as np
        from albumentations.pytorch import ToTensorV2
    except ImportError as error:
        raise RuntimeError("uv sync --extra cure を実行してください") from error

    pipeline = A.Compose(
        [
            A.SmallestMaxSize(max_size=390, interpolation=cv2.INTER_CUBIC, p=1.0),
            A.CenterCrop(height=390, width=390, p=1.0),
            A.Resize(height=336, width=336, interpolation=cv2.INTER_CUBIC, p=1.0),
            A.ImageCompression(quality_range=(70, 70), p=1.0),
            A.Normalize(mean=(0.5, 0.5, 0.5), std=(0.5, 0.5, 0.5)),
            ToTensorV2(),
        ]
    )
    return pipeline(image=np.asarray(image.convert("RGB")))["image"]


def preprocess_image(path: Path) -> Any:
    path = Path(path).expanduser()
    with Image.open(path) as source:
        is_png = source.format == "PNG"
        image = source.convert("RGB")
        image.load()
    if is_png:
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=96)
        buffer.seek(0)
        with Image.open(buffer) as decoded:
            image = decoded.convert("RGB")
            image.load()
    return preprocess(image)


def adapter_path(
    cache_dir: Path | None = None, *, checkpoint: Path | None = None
) -> Path:
    if checkpoint is not None:
        path = Path(checkpoint).expanduser()
        if not path.is_file():
            raise ValueError(f"CuReの重みが見つかりません: {path}")
    else:
        path = (
            (cache_dir or default_cache_dir())
            / MODEL
            / SOURCE_COMMIT
            / "cure_adapter.pt"
        )
        if not path.is_file():
            _download(ADAPTER_URL, path)
    if file_sha256(path) != ADAPTER_SHA256:
        raise ValueError(
            f"重みのSHA-256が一致しません。キャッシュを確認してください: {path}"
        )
    return path


def _resolve_base_checkpoint(
    base_checkpoint: Path | None = None, *, cache_dir: Path | None = None
) -> Path:
    if base_checkpoint is not None:
        path = Path(base_checkpoint).expanduser()
        if not path.is_file():
            raise ValueError(f"基盤モデルが見つかりません: {path}")
    else:
        try:
            from huggingface_hub import hf_hub_download
        except ImportError as error:
            raise RuntimeError("uv sync --extra cure を実行してください") from error
        path = Path(
            hf_hub_download(
                BASE_REPO_ID,
                BASE_FILENAME,
                revision=BASE_REVISION,
                cache_dir=str(
                    (cache_dir or default_cache_dir()) / MODEL / SOURCE_COMMIT
                ),
            )
        )
    if file_sha256(path) != BASE_SHA256:
        raise ValueError(f"CuRe基盤重みのSHA-256が一致しません: {path}")
    return path


def load_model(
    cache_dir: Path | None = None,
    *,
    adapter_checkpoint: Path | None = None,
    base_checkpoint: Path | None = None,
    device: str = "cpu",
) -> Any:
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    resolved = torch.device(device)
    if resolved.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDAを利用できません")
    model = CuRe().float()
    expected = set(model.state_dict())
    base_path = _resolve_base_checkpoint(base_checkpoint, cache_dir=cache_dir)
    base_state = torch.load(
        base_path,
        map_location="cpu",
        weights_only=True,
    )
    prefix = "visual."
    state = {
        "backbone." + name[len(prefix) :]: value
        for name, value in base_state.items()
        if name.startswith(prefix) and "backbone." + name[len(prefix) :] in expected
    }
    adapter = torch.load(
        adapter_path(cache_dir, checkpoint=adapter_checkpoint),
        map_location="cpu",
        weights_only=True,
    )
    overlap = sorted(set(state) & set(adapter))
    if overlap:
        raise RuntimeError(f"Adapter overrides frozen backbone weights: {overlap[:3]}")
    state.update(adapter)
    model.load_state_dict(state, strict=True)
    model.requires_grad_(False)
    return model.eval().to(resolved)


def infer(
    path: Path,
    *,
    cache_dir: Path | None = None,
    model: Any = None,
    adapter_checkpoint: Path | None = None,
    base_checkpoint: Path | None = None,
    device: str = "cpu",
) -> float:
    if model is None:
        model = load_model(
            cache_dir,
            adapter_checkpoint=adapter_checkpoint,
            base_checkpoint=base_checkpoint,
            device=device,
        )
    tensor = preprocess_image(path).unsqueeze(0)
    target = next(model.parameters()).device
    with torch.inference_mode():
        logits = model(tensor.to(target))
    return float(logits.softmax(dim=1)[0, 1].item())


def measure(
    path: Path,
    *,
    image_id: str | None = None,
    device: str = "cpu",
    cache_dir: Path | None = None,
    expected_sha256: str | None = None,
    model: Any = None,
    model_error: Exception | None = None,
    adapter_checkpoint: Path | None = None,
    base_checkpoint: Path | None = None,
) -> dict[str, Any]:
    path = Path(path).expanduser()
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    libraries = {}
    for name in (
        "torch",
        "Pillow",
        "numpy",
        "albumentations",
        "opencv-python-headless",
        "huggingface_hub",
    ):
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
        "weights_version": (
            f"{SOURCE_COMMIT}:sha256:{ADAPTER_SHA256}"
            f"+base:{BASE_REPO_ID}/{BASE_FILENAME}@{BASE_REVISION}"
            f":sha256:{BASE_SHA256}"
        ),
        "preprocessing_version": PREPROCESSING_VERSION,
        "preprocessing": dict(PREPROCESSING),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "device": device,
            "cuda_runtime": torch.version.cuda,
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
        if model_error is not None:
            raise model_error
        score = infer(
            path,
            cache_dir=cache_dir,
            model=model,
            adapter_checkpoint=adapter_checkpoint,
            base_checkpoint=base_checkpoint,
            device=device,
        )
        if not math.isfinite(score):
            raise ValueError("モデルが有限数値ではないスコアを返しました")
        if torch.device(device).type == "cuda":
            record["environment"]["accelerator"] = torch.cuda.get_device_name(device)
        record.update(status="ok", raw_score=score)
    except Exception as error:  # noqa: BLE001 - every failed image needs a record
        record["error"] = f"{type(error).__name__}: {error}"
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="CuRe (Apache-2.0) のCPU既定計測。CUDAも指定できます。スコアは確率ではありません。"
    )
    parser.add_argument("image", type=Path)
    parser.add_argument("--image-id")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--adapter-checkpoint", type=Path)
    parser.add_argument("--base-checkpoint", type=Path)
    parser.add_argument("--output", default="-")
    args = parser.parse_args(argv)
    record = measure(
        args.image,
        image_id=args.image_id,
        device=args.device,
        cache_dir=args.cache_dir,
        adapter_checkpoint=args.adapter_checkpoint,
        base_checkpoint=args.base_checkpoint,
    )
    payload = json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n"
    if args.output == "-":
        print(payload, end="")
    else:
        Path(args.output).write_text(payload, encoding="utf-8")
    return 0 if record["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
