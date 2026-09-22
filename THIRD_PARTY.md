# Third-party components

- [c2pa-python](https://github.com/contentauth/c2pa-python), version 0.37.10 — MIT OR Apache-2.0.
- [TypeSafe Python SDK](https://github.com/typesafe-ai/typesafe-sdk-python), version 0.7.1 — see the upstream package license.
- [UniversalFakeDetect](https://github.com/WisconsinAIVision/UniversalFakeDetect), commit `030495aea3300a8b54c0ec37ec7fe1dd7e63c619` — MIT.
- [OpenAI CLIP](https://github.com/openai/CLIP), ViT-L/14 weights downloaded by UniversalFakeDetect — MIT code; review the model terms before service deployment.

UniversalFakeDetect is downloaded from its pinned official commit on first use. The source archive and published classifier head are checked against SHA-256 values before execution.

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
