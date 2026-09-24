# Issue #62: SNS耐性検出器 (EFFORT) の同一コホート評価 (2026-09-24)

Issue #60 の結論 (UFD / CF / CuRe は SNS 加工で構造的に死ぬ) を受け、
SNS 耐性をうたう外部検出器を同一台帳 (`sns-q75.jsonl`、715行) で計測した。
動いたのは **EFFORT** のみである。結論: EFFORT も較正 `unmet` であり、
商用判定には届かない。ただし誤検知 0 動作点の生成検出は 2/91 群で、
CF (1/91 群) をわずかに上回った (参考値の域を出ない)。

## 1. 候補調査の記録

| 候補 | 公開状況 | 結果 |
| --- | --- | --- |
| So-Fake-R1 | Issue 記載の `github.com/lostpanda85/So-Fake-R1` は **404**。実体は `https://github.com/hzlsaber/So-Fake` (`sofake_r1/` 以下に inference code、論文 arXiv:2505.18660)。重みは HF `saberzl/So-Fake-R1` (LoRA adapter 約330MB) + ベース `Qwen/Qwen2.5-VL-7B-Instruct` が別途必要。推論は CUDA 前提の9段階 VLM パイプライン (Observer / Provider / Decision Maker) で、依存に `ms-swift` 等を含む | 当環境 (CPU のみ) で 715 群の VLM 推論は非現実的 (1画像あたり2回の7B VLM呼び出し)。重み DL・環境構築まで行わず見送り |
| GlobalForge (RealDeg-Bench) | 論文 arXiv:2607.14684。公開は二重盲検の匿名ミラー `https://anonymous.4open.science/r/GlobalForge-BE0F/` のみで、静的取得では JS シェル (`Anonymous Github`) しか返さない。`github.com` 上の実体・HF リポジトリ・直リンク重みは見つからず | 重み URL を特定できず見送り |
| EFFORT (ICML 2025) | `https://github.com/YZY-stack/Effort-AIGI-Detection` (CC BY-NC 4.0、論文 arXiv:2411.15633)。コードは当該リポジトリのみ、重みは Google Drive 配布。汎用 AIGI 用 (CLIP-L/14 + Effort、GenImage sdv1.4 学習) を使用 | **計測に成功**。CLIP 単一 forward のため CPU で 715 群を約16分で処理 |

外部リポジトリのコードは vendoring していない。計測は `scripts/measure_effort.py`
が `/tmp/effort` の checkout を実行時 import する (SVD 変換関数のみ利用し、
モデル本体の配線はスクリプト内の対応する最小構成で再現。詳細は §5)。

## 2. EFFORT 計測条件

- EFFORT checkout: `/tmp/effort`、commit `96f5dea2b534d400cfd7003f053c7e93c8e16461`
  (スクリプトが起動時にピン留めと照合し、不一致なら計測しない)
- 重み: Google Drive `1UXf1hC9FC1yV93uKwXSkdtepsgpIAU9d`
  (README 記載の General AIGI 用 = CLIP-L/14 + Effort、GenImage sdv1.4 学習)、
  SHA-256 `7c32ceb4e66d303050e8fc5dc7543fa347693fb4ee6b5df4d6eaf9f6a92fb813`、
  約1.21GB。`~/.cache/detecter/effort/<commit>/effort-genimage-sdv14.pth` に保存
- 注意: DL した重みの state dict は `UniversalFakeDetect_Benchmark` の
  `ClipModel` (単一 logit) ではなく **DeepfakeBench 系 `EffortDetector`**
  (vision backbone + 2クラス head、DataParallel `module.` 接頭辞) の配置だった。
  そのため strict load は `backbone` + `head` 構成に対して行い、
  `raw_score = softmax(logits, dim=1)[1]` (fake 確率) とした。
  上流 `demo.py` の `prob` 定義と同一である
- ベース CLIP: `openai/clip-vit-large-patch14` revision
  `32bd64288804d66eefd0ccbe215aa642df71cc41`
  (strict load で全量上書きされるため初期値に意味はない。条件記録用)
- 前処理 (学習時の `abstract_dataset.load_rgb` と同一):
  RGB + EXIF transpose → 224×224 リサイズ (CUBIC) → ToTensor →
  CLIP 平均・分散で正規化。face alignment・center crop・tiling はなし
- 実行環境: Python 3.11.6 / macOS CPU / torch 2.2.2 / torchvision 0.17.2 /
  transformers 4.57.6 / loralib 0.1.2 / Pillow 11.3.0。
  追加依存は `uv pip install --python .venv/bin/python "transformers>=4.40,<5" loralib gdown`
  で導入 (pyproject の extra 化は未実施。再現時は同コマンドを用いること)
- 計測: `.venv/bin/python scripts/measure_effort.py
  --ledger /tmp/detecter-issue60/sns-q75.jsonl
  --output /tmp/detecter-issue62-effort.jsonl`
  → 715行・全件 `ok`、条件は1種類のみ。所要約16分 (CPU)

## 3. 較正 (tuning 569行 → 556群: 実写465群・生成91群)

`detecter.calibration` (split=tuning、群単位、生成は min・実写は max 方式) の結果:

| 検出器 | status | しきい値 | 実写誤検知 | 生成検出 |
| --- | --- | --- | --- | --- |
| EFFORT | `unmet` | 0.9972 (fake確率) | 0/465群 | 2/91群 (2.2%、GPT 2・NB 0) |
| Community Forensics | `unmet` | -0.5593 (logit) | 0/465群 | 1/91群 (1.1%、NBのみ) |
| CuRe | `unmet` | 0.9999 | 0/465群 | 0/91群 |
| UFD | `unmet` | 0.9936 | 0/465群 | 0/91群 |

低 FPR 運用の参考 (tuning 群単位、しきい値は較正 candidates から選択):

| 動作点 | しきい値 | 実写FP | 生成検出 | 内訳 |
| --- | --- | --- | --- | --- |
| FPR≈0% (FP 0) | 0.9972 | 0/465 | 2/91 (2.2%) | GPT 2・NB 0 |
| FPR≦1% (FP≦4) | 0.9902 | 4/465 | 9/91 (9.9%) | GPT 4・NB 5 |

スコア分布 (画像単位、参考):

| 対象 | 平均 | 最小 | 最大 |
| --- | --- | --- | --- |
| 実写 (600行) | 0.541 | 0.001 | 0.997 |
| 生成 (115行) | 0.771 | 0.100 | 0.999 |

- 実写と生成の平均は離れている (0.54 vs 0.77) が裾が大きく重なり、
  誤検知 0 点では裾の2群しか拾えない。
- CF と逆の生成器偏りがある: FP0 点では GPT のみ2群を検出 (CF は NB のみ1群)。
  ただし裾の2群であり、安定した得意不得意とは言えない (§4 参照)。

## 4. evaluation 群への参考適用 (正式値ではない)

tuning 較正は `unmet` のため正式な判定適用はできない
(`validate_config` が拒否し、適用しても全件 `inconclusive` になるのは
#60 と同一構図)。以下は tuning しきい値をそのまま当てた情報値である
(群単位、生成は全画像陽性・実写は1画像陽性を陽性とする #60 と同一方針):

| しきい値 | 実写誤検知 | 生成検出 | 内訳 |
| --- | --- | --- | --- |
| 0.9972 (tuning FP0) | 0/121群 | 2/24群 | NB 2 (tuning では GPT 2 だった) |
| 0.9902 (tuning FPR≦1%) | 1/121群 | 2/24群 | NB 2 |

- tuning FP0 点の実写 FP 0 は evaluation に汎化した (0/121群) が、
  検出は 2/24群にとどまり、検出された生成器も tuning (GPT) と evaluation (NB)
  で一致しない。裾のしきい値であり汎化は偶然の域である。
- 正式手順の `evaluation` / `evaluate-pipeline` は未実行。
  実行しても較正 `unmet` のため `not_measured` / `not_met` になるのは確定している。

## 5. 実装メモ (`scripts/measure_effort.py`)

- 出力は `detecter.comparison` と同一スキーマ
  (`image_id` / `sha256` / `model` / `raw_score` / `status` /
  `model_version` / `weights_version` / `preprocessing_version` /
  `preprocessing` / `environment` / `observed_sha256` /
  `source_image_id` / `source_sha256` / `history`)。
  `calibration` の条件照合 (`model`・`model_version`・`weights_version`・
  `preprocessing_version` の一致) を通過済み
- `model`: `effort`、`model_version`: EFFORT commit、
  `weights_version`: `<commit>:drive:<file-id>:sha256:<ckpt> + base:<repo>@<rev>`、
  `preprocessing_version`: `<commit>:effort-clip-l14-resize224-rgb-exif-v1`
- 上流コードの利用は `apply_svd_residual_to_self_attn` の実行時 import のみ
  (DeepfakeBench 系の同名関数と推論上等価な `UniversalFakeDetect_Benchmark`
  側の実装を利用)。`backbone` + 2クラス `head` の配線はスクリプト内で再現し、
  重みの `module.` 接頭辞を除去して strict load する
- ラベルは推論に一切渡さない (`ufd_batch.load_inputs` で射影した
  `image_id` / `sha256` / `path` のみ使用)

## 6. 結論

- SNS 耐性候補のうち実測できたのは EFFORT のみ。
  So-Fake-R1 は重量 VLM 系で当環境では不可、GlobalForge は重み取得経路がなく不可
  (いずれも §1 に記録)。
- EFFORT は FP0 点で 2/91群と CF (1/91群) をわずかに上回るが、
  較正 `unmet`・FPR≦1% でも 9/91群 (9.9%) であり、目標
  (実写誤検知率 0.1% 以下かつ生成検出率 90% 以上) には遠く及ばない。
- CF と逆向きの生成器偏り (FP0 点で GPT のみ) が見えたが、裾の2群であり、
  アンサンブル根拠にするには弱い。OR 検証は未実施。
- 検出器の差し替えだけでは SNS 条件の採用基準に届かないことが再確認された。
  実写の増強とセットでの検討が必要 (cf. `docs/cohort-issue60-sns-derived.md` §7)。

## 成果物 (いずれも `/tmp`、リポジトリには含めない)

- `/tmp/detecter-issue62-smoke-ledger.jsonl` (2行)、`-smoke.jsonl` (疎通)
- `/tmp/detecter-issue62-effort.jsonl` (715行、全件 `ok`)
- `/tmp/detecter-issue62-effort-tuning.jsonl` (569行)
- `/tmp/detecter-issue62-effort-config.json` (`unmet`、しきい値 0.9972)

## 再現手順

```sh
git clone --depth 1 https://github.com/YZY-stack/Effort-AIGI-Detection.git /tmp/effort
# commit 96f5dea2b534d400cfd7003f053c7e93c8e16461 を確認
uv pip install --python .venv/bin/python "transformers>=4.40,<5" loralib gdown
.venv/bin/python scripts/measure_effort.py \
  --ledger /tmp/detecter-issue60/sns-q75.jsonl \
  --output /tmp/detecter-issue62-effort.jsonl
# tuning 抽出は image_id 突合せ (#60 と同方式)
.venv/bin/python -m detecter.calibration \
  --ledger /tmp/detecter-issue60/tuning-ledger.jsonl \
  --measurements /tmp/detecter-issue62-effort-tuning.jsonl \
  --split tuning --output /tmp/detecter-issue62-effort-config.json
```
