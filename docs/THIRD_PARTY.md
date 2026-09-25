# Third-party components

## EFFORT (measurement script only, no vendored code)

- [Effort-AIGI-Detection](https://github.com/YZY-stack/Effort-AIGI-Detection), commit `96f5dea2b534d400cfd7003f053c7e93c8e16461` — CC BY-NC 4.0 (evaluation use only; not for service deployment).
- [General-AIGI weights (CLIP-L/14 + Effort, GenImage sdv1.4)](https://drive.google.com/file/d/1UXf1hC9FC1yV93uKwXSkdtepsgpIAU9d/view?usp=sharing), SHA-256 `7c32ceb4e66d303050e8fc5dc7543fa347693fb4ee6b5df4d6eaf9f6a92fb813` — same CC BY-NC 4.0 terms as the repository.
- [Base model](https://huggingface.co/openai/clip-vit-large-patch14), revision `32bd64288804d66eefd0ccbe215aa642df71cc41` — MIT code; review the model terms before service deployment.

`scripts/measure_effort.py` imports only the SVD-residual transform from an
external checkout of the pinned commit at runtime and reimplements the
backbone-plus-head wiring. No upstream file is copied into this repository.
The checkpoint layout matches the DeepfakeBench-framework `EffortDetector`
(`backbone` + two-class `head`), so scores are
`softmax(logits, dim=1)[1]` (fake probability), matching upstream `demo.py`.

- [c2pa-python](https://github.com/contentauth/c2pa-python), version 0.37.10 — MIT OR Apache-2.0.
- [TypeSafe Python SDK](https://github.com/typesafe-ai/typesafe-sdk-python), version 0.7.1 — see the upstream package license.
- [UniversalFakeDetect](https://github.com/WisconsinAIVision/UniversalFakeDetect), commit `030495aea3300a8b54c0ec37ec7fe1dd7e63c619` — MIT.
- [pillow-heif](https://github.com/bigcat88/pillow_heif), version 1.8.0 — BSD-3-Clause. HEIC/HEIFのデコードに利用します。
- [OpenAI CLIP](https://github.com/openai/CLIP), ViT-L/14 weights downloaded by UniversalFakeDetect — MIT code; review the model terms before service deployment.

UniversalFakeDetect is downloaded from its pinned official commit on first use. The source archive and published classifier head are checked against SHA-256 values before execution.

## CuRe

- [Official code](https://github.com/manic-cui/CuRe/tree/8f7832c83dcd3f4f89de955103e94a64ddc3cdc9), commit `8f7832c83dcd3f4f89de955103e94a64ddc3cdc9` — Apache-2.0.
- [Official adapter](https://github.com/manic-cui/CuRe/blob/8f7832c83dcd3f4f89de955103e94a64ddc3cdc9/weights/cure_adapter.pt), same commit — Apache-2.0, SHA-256 `17cabb334563c15abc8827db87dc272a4aef10f4279025faee1ef8d32c444ae1`.
- [Base model](https://huggingface.co/facebook/PE-Core-L14-336), file `PE-Core-L14-336.pt` (about 2.7 GB), revision `bafb0f76541d399057e980a25947f67acec76575`, SHA-256 `0cdab5b338cbaa1e7a5dcd1b2fb4c9f4d5df1abd289564658edbab64a650e7e8` — Apache-2.0.
- [albumentations](https://github.com/albumentations-team/albumentations/tree/2.0.8), version 2.0.8 — MIT.
- [opencv-python-headless](https://github.com/opencv/opencv-python), version 4.x — Apache-2.0.
- [huggingface_hub](https://github.com/huggingface/huggingface_hub), version 0.23 or newer — Apache-2.0.

The vision backbone in `src/detecter/cure.py` adapts the pinned official
`cure/backbone.py`, itself adapted from Perception Encoder by Meta Platforms,
Inc. and affiliates under the Apache License 2.0. Preprocessing adapts the
pinned official `cure/preprocess.py`; PNG inputs are identified by decoded
format instead of filename suffix.
The Apache-2.0 license text and the upstream PE Core notice are included in
`LICENSES/Apache-2.0.txt` and `LICENSES/PE-Core-NOTICE.txt`.
CuRe ships as the optional `cure` extra so the existing UFD and Community
Forensics execution paths keep their pinned dependencies.

## Community Forensics 384

- [Official code](https://github.com/JeongsooP/Community-Forensics/tree/ee5b71d43db0f3779e1edd64ee927b13f2dd6ad4), commit `ee5b71d43db0f3779e1edd64ee927b13f2dd6ad4` — MIT.
- [Official weights](https://huggingface.co/OwensLab/commfor-model-384/tree/6076002bf0d9dd37537f965ee2f06f826c333b61), revision `6076002bf0d9dd37537f965ee2f06f826c333b61` — MIT, as stated in the pinned model card.
- [timm](https://github.com/huggingface/pytorch-image-models/tree/v1.0.15), version 1.0.15 — Apache-2.0.
- [safetensors](https://github.com/huggingface/safetensors/tree/v0.5.3), version 0.5.3 — Apache-2.0.

The model structure and test preprocessing in `src/detecter/community_forensics.py`
follow the pinned official implementation. The optional verification script downloads
and checksums the original inference definitions. The MIT notice follows:

MIT License

Copyright (c) 2025 Jeongsoo Park

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## EFFORT (Effort-AIGI-Detection)

- [Official code](https://github.com/YZY-stack/Effort-AIGI-Detection), commit `96f5dea2b534d400cfd7003f053c7e93c8e16461` — CC BY-NC 4.0 (non-commercial evaluation use only).
- [GenImage sdv1.4 checkpoint](https://drive.google.com/file/d/1UXf1hC9FC1yV93uKwXSkdtepsgpIAU9d/view?usp=sharing), Drive file `1UXf1hC9FC1yV93uKwXSkdtepsgpIAU9d` — CC BY-NC 4.0, SHA-256 `7c32ceb4e66d303050e8fc5dc7543fa347693fb4ee6b5df4d6eaf9f6a92fb813`.
- [Base model](https://huggingface.co/openai/clip-vit-large-patch14), revision `32bd64288804d66eefd0ccbe215aa642df71cc41` — review the model terms before service deployment.
- [loralib](https://github.com/microsoft/LoRA), version 0.1.2 — MIT (required to import the upstream SVD layers).

Upstream code is NOT vendored: `scripts/measure_effort.py` imports the SVD
residual layers at runtime from an external EFFORT checkout pinned to the
commit above, wires the DeepfakeBench `EffortDetector` structure (CLIP
ViT-L/14 vision backbone + 2-class head, softmax fake probability), and
strict-loads the checkpoint after stripping the DataParallel `module.`
prefix. So-Fake-R1 and GlobalForge were deferred (see
`docs/cohort-issue62-robust-detectors.md`): So-Fake-R1 needs CUDA and a
9-stage VLM pipeline (infeasible for 715 CPU groups), and no public weight
URL could be confirmed for GlobalForge.
