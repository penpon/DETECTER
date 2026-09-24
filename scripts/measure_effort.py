"""EFFORT general-AIGI detector (CC BY-NC 4.0) measurements on a ledger.

Upstream code is NOT vendored: the SVD residual layers are imported at runtime
from an external EFFORT checkout (``--effort-repo``, pinned to
``EFFORT_COMMIT``). The measured architecture mirrors upstream DeepfakeBench
``EffortDetector`` (CLIP ViT-L/14 vision backbone with SVD-residual self
attention + 2-class linear head, fake probability via softmax), which is the
codebase whose GenImage sdv1.4 checkpoint is released. The SVD layer math is
forward-identical between the DeepfakeBench and UniversalFakeDetect_Benchmark
copies in the checkout; the latter is imported because it has no heavy
optional dependencies (sklearn/tensorboard/dlib).

Output records follow the ``detecter.comparison`` schema so that
``detecter.calibration`` / ``detecter.evaluation`` can consume them directly.

Upstream: https://github.com/YZY-stack/Effort-AIGI-Detection
Weights: Google Drive file ``DRIVE_FILE_ID`` (CLIP ViT-L/14 + Effort adapter
trained on GenImage sdv1.4). Base CLIP weights come from Hugging Face
(``openai/clip-vit-large-patch14``); every forward-relevant parameter is
overwritten by the strict state-dict load (the ``module.`` DataParallel
prefix is stripped first).
Preprocessing mirrors upstream ``DeepfakeBench`` data pipeline
(whole image resized to 224x224 cubic + CLIP normalization, no crop).

See THIRD_PARTY.md (Effort-AIGI-Detection entry) for license terms.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import platform
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import torch
from PIL import Image

from detecter.core import decoded_image, default_cache_dir, file_sha256, inspect_image
from detecter.ufd_batch import load_inputs

MODEL = "effort"
EFFORT_COMMIT = "96f5dea2b534d400cfd7003f053c7e93c8e16461"
EFFORT_REPO_URL = "https://github.com/YZY-stack/Effort-AIGI-Detection"
DRIVE_FILE_ID = "1UXf1hC9FC1yV93uKwXSkdtepsgpIAU9d"
DRIVE_URL = f"https://drive.google.com/uc?id={DRIVE_FILE_ID}"
CHECKPOINT_NAME = "effort-genimage-sdv14.pth"
BASE_REPO_ID = "openai/clip-vit-large-patch14"
# The Drive checkpoint stores a DeepfakeBench-framework EffortDetector state
# (DataParallel `module.` prefix, `backbone` + 2-class `head`), trained on
# GenImage sdv1.4. Preprocessing mirrors DeepfakeBench abstract_dataset.load_rgb
# (RGB, resize resolution x resolution with INTER_CUBIC) + CLIP normalization.
ARCHITECTURE = "clip-vit-large-patch14 vision tower + svd-residual-r1023 + linear-2"
PREPROCESSING = {
    "color_mode": "RGB",
    "exif_transpose": True,
    "resize": [224, 224],
    "interpolation": "cubic",
    "mean": [0.48145466, 0.4578275, 0.40821073],
    "std": [0.26862954, 0.26130258, 0.27577711],
    "dtype": "float32",
}
PREPROCESSING_VERSION = f"{EFFORT_COMMIT}:effort-clip-l14-resize224-rgb-exif-v1"
IMPLEMENTATION_SHA256 = file_sha256(Path(__file__))


def effort_checkout_commit(repo: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(f"EFFORT checkout のコミットを特定できません: {repo}")
    return result.stdout.strip()


def resolve_checkpoint(cache_dir: Path, checkpoint: Path | None) -> Path:
    if checkpoint is not None:
        path = Path(checkpoint).expanduser()
        if not path.is_file():
            raise ValueError(f"EFFORT の重みが見つかりません: {path}")
        return path
    path = cache_dir / MODEL / EFFORT_COMMIT / CHECKPOINT_NAME
    if not path.is_file():
        try:
            import gdown
        except ImportError as error:
            raise ValueError(
                f"EFFORT の重みがありません。gdown で取得してください: "
                f"{DRIVE_URL} -> {path}"
            ) from error
        path.parent.mkdir(parents=True, exist_ok=True)
        gdown.download(DRIVE_URL, str(path), quiet=False)
    if not path.is_file():
        raise ValueError(f"EFFORT の重みの取得に失敗しました: {path}")
    return path


def load_model(
    repo: Path,
    checkpoint_path: Path,
    *,
    base_repo: str = BASE_REPO_ID,
    hf_cache: Path | None = None,
    device: str = "cpu",
) -> Any:
    actual = effort_checkout_commit(repo)
    if actual != EFFORT_COMMIT:
        raise ValueError(
            f"EFFORT checkout がピン留めと不一致です: {actual} != {EFFORT_COMMIT}"
        )
    benchmark = repo / "UniversalFakeDetect_Benchmark"
    svd_module = benchmark / "models" / "clip_models.py"
    if not svd_module.is_file():
        raise ValueError(f"EFFORT checkout の配置が想定と異なります: {repo}")
    sys.path.insert(0, str(benchmark))
    try:
        from models.clip_models import apply_svd_residual_to_self_attn
    finally:
        sys.path.remove(str(benchmark))
    from transformers import CLIPModel

    base = CLIPModel.from_pretrained(
        base_repo,
        **({"cache_dir": str(hf_cache)} if hf_cache is not None else {}),
    )
    backbone = apply_svd_residual_to_self_attn(base.vision_model, r=1024 - 1)
    del base

    class EffortNet(torch.nn.Module):
        """Wiring mirror of DeepfakeBench EffortDetector (backbone + head)."""

        def __init__(self) -> None:
            super().__init__()
            self.backbone = backbone
            self.head = torch.nn.Linear(1024, 2)

        def forward(self, images: torch.Tensor) -> torch.Tensor:
            features = self.backbone(images)["pooler_output"]
            return self.head(features)

    model = EffortNet()
    raw = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    if isinstance(raw, dict) and set(raw) == {"model"}:
        raw = raw["model"]
    state = {
        key[len("module.") :]: value
        for key, value in raw.items()
        if key.startswith("module.")
    }
    if len(state) != len(raw):
        raise ValueError("チェックポイントの module. 接頭辞が想定と異なります")
    model.load_state_dict(state, strict=True)
    model.requires_grad_(False)
    return model.eval().to(torch.device(device))


def base_revision(base_repo: str = BASE_REPO_ID) -> str:
    try:
        from huggingface_hub import HfApi
    except ImportError:
        return "unknown"
    try:
        return HfApi().model_info(base_repo).sha or "unknown"
    except Exception:  # noqa: BLE001 - record only
        return "unknown"


def preprocess(image: Image.Image) -> Any:
    from torchvision import transforms

    pipeline = transforms.Compose(
        [
            transforms.Resize(
                (224, 224),
                interpolation=transforms.InterpolationMode.BICUBIC,
            ),
            transforms.ToTensor(),
            transforms.Normalize(mean=PREPROCESSING["mean"], std=PREPROCESSING["std"]),
        ]
    )
    return pipeline(image)


def infer(path: Path, *, model: Any) -> float:
    with decoded_image(path) as image:
        tensor = preprocess(image).unsqueeze(0)
    target = next(model.parameters()).device
    with torch.inference_mode():
        logits = model(tensor.to(target))
    return float(logits.softmax(dim=1)[0, 1].item())


def measure(
    path: Path,
    *,
    image_id: str | None = None,
    expected_sha256: str | None = None,
    model: Any = None,
    model_error: Exception | None = None,
    weights_version: str,
    device: str = "cpu",
) -> dict[str, Any]:
    path = Path(path).expanduser()
    libraries: dict[str, str | None] = {}
    for name in (
        "torch",
        "torchvision",
        "Pillow",
        "numpy",
        "transformers",
        "loralib",
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
        "model_version": EFFORT_COMMIT,
        "implementation_sha256": IMPLEMENTATION_SHA256,
        "weights_version": weights_version,
        "preprocessing_version": PREPROCESSING_VERSION,
        "preprocessing": deepcopy(PREPROCESSING),
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
        if model is None:
            raise ValueError("model is required")
        score = infer(path, model=model)
        if not math.isfinite(score):
            raise ValueError("モデルが有限数値ではないスコアを返しました")
        record.update(status="ok", raw_score=score)
    except Exception as error:  # noqa: BLE001 - every failed image needs a record
        record["error"] = f"{type(error).__name__}: {error}"
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "EFFORT (CLIP-L/14 + SVD residual、GenImage sdv1.4 学習) で台帳を計測します。"
            "raw_score は fake 確率です。"
        )
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--effort-repo", type=Path, default=Path("/tmp/effort"))
    parser.add_argument("--checkpoint", type=Path, default=None)
    parser.add_argument("--cache-dir", type=Path, default=default_cache_dir())
    parser.add_argument("--base-repo", default=BASE_REPO_ID)
    parser.add_argument("--device", choices=("cpu", "auto", "cuda"), default="cpu")
    args = parser.parse_args(argv)
    device = args.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    inputs = sorted(load_inputs(args.ledger), key=lambda row: row["image_id"])
    checkpoint_path = resolve_checkpoint(args.cache_dir, args.checkpoint)
    checkpoint_sha256 = file_sha256(checkpoint_path)
    revision = base_revision(args.base_repo)
    weights_version = (
        f"{EFFORT_COMMIT}:drive:{DRIVE_FILE_ID}:sha256:{checkpoint_sha256}"
        f"+base:{args.base_repo}@{revision}"
    )
    try:
        model: Any = load_model(
            args.effort_repo,
            checkpoint_path,
            base_repo=args.base_repo,
            hf_cache=args.cache_dir / MODEL / "hf-clip" / "hub",
            device=device,
        )
        model_error: Exception | None = None
    except Exception as error:  # noqa: BLE001 - keep per-image records
        model, model_error = None, error
    records = []
    for row in inputs:
        record = measure(
            Path(row["path"]),
            image_id=row["image_id"],
            expected_sha256=row["sha256"],
            model=model,
            model_error=model_error,
            weights_version=weights_version,
            device=device,
        )
        record.update(
            source_image_id=row.get("source_image_id", row["image_id"]),
            source_sha256=row.get("source_sha256", row["sha256"]),
            history=row.get("history", []),
        )
        records.append(record)
    if str(args.output) != "-":
        args.output.parent.mkdir(parents=True, exist_ok=True)
    stream = (
        sys.stdout
        if str(args.output) == "-"
        else args.output.open("x", encoding="utf-8")
    )
    try:
        for record in records:
            stream.write(
                json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False)
                + "\n"
            )
    finally:
        if stream is not sys.stdout:
            stream.close()
    return 1 if any(r["status"] == "error" for r in records) else 0


if __name__ == "__main__":
    raise SystemExit(main())
