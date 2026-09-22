"""Opt-in CPU comparison against pinned upstream definitions; downloads weights."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import tempfile
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import timm
import torch
from huggingface_hub import PyTorchModelHubMixin
from PIL import Image
from safetensors.torch import load_file
from torchvision import transforms
from torchvision.transforms import functional

from detecter.community_forensics import (
    SOURCE_COMMIT,
    measure,
    preprocess,
    weights_path,
)

SOURCES = {
    "models.py": (
        "988f2f566aa4c177dd845bfccdab9eac2b3fa5174649332b09ee8cc840c8bb97",
        {"ViTClassifier"},
    ),
    "custom_transforms.py": (
        "85e49fee816b20859d6f1f96fbe51d296c2d4c7b6c371326b764f57a58a25bdb",
        {"ToTensor_range"},
    ),
    "dataloader.py": (
        "e33032c6bf5e18c5ae3ae0a0391a8571a7bb2cfa4b140c0eb80f5ce86f14562b",
        {"determine_resize_crop_sizes", "get_transform"},
    ),
}


def official_definitions() -> dict[str, Any]:
    namespace: dict[str, Any] = {
        "torch": torch,
        "nn": torch.nn,
        "timm": timm,
        "PyTorchModelHubMixin": PyTorchModelHubMixin,
        "Tensor": torch.Tensor,
        "F": functional,
        "transforms": transforms,
    }
    for filename, (sha256, names) in SOURCES.items():
        url = f"https://raw.githubusercontent.com/JeongsooP/Community-Forensics/{SOURCE_COMMIT}/{filename}"
        with urllib.request.urlopen(url, timeout=120) as response:
            source = response.read()
        if hashlib.sha256(source).hexdigest() != sha256:
            raise ValueError(f"Official source checksum mismatch: {filename}")
        # Execute unchanged inference definitions, not unrelated training imports.
        tree = ast.parse(source, filename=filename)
        tree.body = [
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names
        ]
        exec(compile(tree, filename, "exec"), namespace)  # noqa: S102 - checksum-verified official definitions
        if "ToTensor_range" in namespace:
            namespace["ctrans"] = SimpleNamespace(
                ToTensor_range=namespace["ToTensor_range"]
            )
    return namespace


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path)
    args = parser.parse_args()
    official = official_definitions()
    create_model = timm.create_model

    def without_redundant_backbone(*positional: Any, **keywords: Any) -> Any:
        keywords["pretrained"] = False
        return create_model(*positional, **keywords)

    # The complete official checkpoint replaces every parameter, verified strictly.
    # Skip only the otherwise discarded ImageNet backbone download.
    with patch.object(timm, "create_model", side_effect=without_redundant_backbone):
        reference = official["ViTClassifier"](device="cpu")
    reference.load_state_dict(
        load_file(str(weights_path(args.cache_dir)), device="cpu"), strict=True
    )
    reference.eval()
    transform = official["get_transform"](SimpleNamespace(input_size=384), mode="test")
    results = []
    with tempfile.TemporaryDirectory(prefix="commfor-verification-") as temporary:
        for index, (width, height, mode) in enumerate(
            ((37, 53, "RGB"), (81, 29, "RGBA"), (48, 48, "L"))
        ):
            image = Image.new("RGB", (width, height))
            image.putdata(
                [
                    ((x * 17 + y * 3) % 256, (y * 29) % 256, (x * y) % 256)
                    for y in range(height)
                    for x in range(width)
                ]
            )
            image = image.convert(mode)
            path = Path(temporary) / f"synthetic-{index}.png"
            image.save(path)
            expected_tensor = transform(image.convert("RGB"))
            torch.testing.assert_close(
                preprocess(image), expected_tensor, atol=0, rtol=0
            )
            with torch.inference_mode():
                expected = float(reference(expected_tensor.unsqueeze(0)).item())
            record = measure(
                path, image_id=f"synthetic-{index}", cache_dir=args.cache_dir
            )
            if record["status"] != "ok":
                raise RuntimeError(record["error"])
            actual = record["raw_score"]
            if not math.isclose(actual, expected, rel_tol=1e-5, abs_tol=1e-5):
                raise AssertionError(f"Official {expected} != implementation {actual}")
            results.append(
                {
                    "image_id": record["image_id"],
                    "mode": mode,
                    "official_logit": expected,
                    "raw_score": actual,
                    "absolute_error": abs(actual - expected),
                }
            )
    print(
        json.dumps(
            {
                "status": "ok",
                "atol": 1e-5,
                "rtol": 1e-5,
                "source_commit": SOURCE_COMMIT,
                "environment": record["environment"],
                "comparisons": results,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
