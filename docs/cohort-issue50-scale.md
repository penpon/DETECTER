# Issue #50 スケール拡大評価結果 (2026-09-24)

Issue #48 の後続として `ai-picture` を増量し、生成器別 evaluation
10 群以上の要求を充足させた上で `cohort build` → `ufd_batch` →
`calibration` → `evaluation` → `evaluate-pipeline` を再実行した記録である。
画像本体はリポジトリに入れず、台帳・計測・判定は
`/tmp/detecter-issue50-*` に保存した。

## 生成の増量

- 新規 TSV `/tmp/detecter-issue50-manifest.tsv` (50 行) を
  `scripts/generate_ai_pictures.py` で実行し、失敗 0 件。
  - `gpt-image-2-033.png` 〜 `gpt-image-2-057.png` (25 枚、
    `gpt_image_2` / low / 1k)
  - `nano-banana-032.png` 〜 `nano-banana-056.png` (25 枚、`nano_banana`)
  - プロンプトは日本の日常スマホ写真 (食事、街、室内、乗り物、季節の風景、
    手元アップなど) で多様化。アスペクト比は 4:3 中心に 1:1 / 3:4 / 16:9
    を混在。
- `ai-picture` は 65 枚 → 115 枚
  (GPT Image 2 系 58 枚 = 連番 57 + テスト 1、
  Nano Banana 系 57 枚 = 連番 56 + テスト 1)。
- テスト画像 (`*-test01.png`) は前回と同様に各モデルの inventory に含めた。

## 台帳構成

`/tmp/detecter-issue50-inv-ai.jsonl` (115 行) を `cohort scan` で作成し、
ファイル名で `/tmp/inv-gpt.jsonl` (58 行) と
`/tmp/inv-nb.jsonl` (57 行) に分割した
(前回の同名ファイルは本評価の 115 枚版で上書き)。
マニフェストは `/tmp/detecter-issue50-cohort-manifest.json`
(前回の `/tmp/detecter-cohort-manifest.json` と同内容) を使い、
`--seed 20260924 --evaluation-fraction 0.2` で自動分割した。

素の自動分割では行数増加によるカット位置の移動で実写 2 群の割当てが
前回からずれた (tuning 85 / evaluation 20) ため、実写 105 行の `split` は
sha256 照合で前回台帳の割当てに復元した。生成行の seed 分割はそのままとした。
最終台帳: `/tmp/detecter-issue50-ledger.jsonl` (220 行)。

| ラベル | tuning | evaluation |
| --- | --- | --- |
| 実写 | 83 群 (前回と同一割当て) | 22 群 (前回と同一割当て) |
| GPT Image 2 | 45 群 | 13 群 |
| Nano Banana | 46 群 | 11 群 |
| 生成計 | 91 群 | 24 群 |

`generator_groups` 充足は両モデルとも `met`
(GPT Image 2: 13/10、Nano Banana: 11/10)。
tuning 側にも各モデル 40 群以上が残るため `calibrate_records` の
生成群要件も満たす。

## 計測

前回計測 `/tmp/detecter-issue48-measurements.jsonl` (159 件) は sha256 照合で
全件再利用した (モデル・重み・前処理条件が同一であることを確認)。
新規 61 件のみ `ufd_batch` で計測し
(`/tmp/detecter-issue50-measurements-new.jsonl`、失敗 0)、
`image_id` を新台帳に付け替えて結合した。
計測: `/tmp/detecter-issue50-measurements.jsonl` (220 件全件 `ok`)。
モデル条件は全行同一
(`model: ufd`、`preprocessing_version: ufd-rgb-exif-center224-clip-normalize-v2`)。

## 較正 (tuning 174 群)

tuning 行だけの台帳 (`/tmp/detecter-issue50-tuning-ledger.jsonl`) と
計測 (`/tmp/detecter-issue50-tuning-measurements.jsonl`) で
`python -m detecter.calibration --split tuning` を実行した。
結果は `status: unmet`、しきい値 0.9914 (前回と同一値)、
実写誤検知 0/83 群、全体生成検出 0/91 群
(設定: `/tmp/detecter-issue50-decision-config.json`)。

tuning 群単位 (実写は群内最大、生成は群内最小) のしきい値別成績の推移:

| しきい値 | 実写誤検知 (#48 → #50) | 生成検出 (#48 → #50) |
| --- | --- | --- |
| 0.9 | 9/83 → 9/83 (10.8%) | 0/44 → 1/91 (1.1%) |
| 0.5 | 29/83 → 29/83 (34.9%) | 1/44 → 3/91 (3.3%) |
| 0.1 | 41/83 → 41/83 (49.4%) | 5/44 → 17/91 (18.7%) |
| 0.01 | 64/83 → 64/83 (77.1%) | 22/44 → 43/91 (47.3%) |

実写側の数値は母集団・割当てが同一のため不変。
生成側は分母が 44 → 91 群に倍増し、しきい値を下げれば半数近くが検出される
ようになったが、誤検知率 0.1% 以下と検出率 90% 以上を同時に満たす候補は
依然存在しない。実写の上位スコア (0.99 など) が生成画像の上位を上回る
構造は変わっていない。

参考: 生成画像の最高スコアは新規分の `gpt-image-2-044.png`
(カウンター席のラーメン接写) で 0.93。新規 61 枚の平均スコア 0.08 は
既存 54 枚の平均 0.07 とほぼ同じ分布であり、プロンプト多様化による
検出されやすさの変化は見られない。

## 最終評価 (evaluation 46 群)

未達設定は判定に適用しない仕様のため、evaluation 46 件の判定記録
(`/tmp/detecter-issue50-eval-decisions.jsonl`) は全件 `inconclusive`
(理由 `config_invalid`)。`detecter.evaluation --unit source_group
--split evaluation` の結果 (`/tmp/detecter-issue50-evaluation.json`):

| 指標 | 分子/分母 (#48 → #50) | 状態 |
| --- | --- | --- |
| 実写誤検知率 | 判定不能 (分母 0、22 群を `config_invalid` で除外) | `not_measured` (変化なし) |
| 全体生成検出率 | 0/10 → 0/24 | `measured` (0.0) |
| 部分編集検出率 | 対象なし | `insufficient_data` (変化なし) |
| 実行失敗率 | 0/32 → 0/46 | `measured` |
| 保留率 | 32/32 → 46/46 | `measured` |

生成器別の検出率:

| 生成器 | 検出 (#48 → #50) | 点推定 | 95% 上限 (片側、参考) |
| --- | --- | --- | --- |
| GPT Image 2 | 0/4 群 → 0/13 群 | 0.0 | 約 20.6% |
| Nano Banana | 0/6 群 → 0/11 群 | 0.0 | 約 23.8% |
| 全体生成 | 0/10 群 → 0/24 群 | 0.0 | 約 11.7% |

`detecter evaluate-pipeline` の結果
(`/tmp/detecter-issue50-pipeline.json`) は `status: not_met`。
`generator_coverage` は両モデルとも `met` となり、前回の
`generator_group_insufficient:GPT Image 2` /
`generator_group_insufficient:Nano Banana` は解消した。
残る未検証理由は `decision_config_invalid` のみである。

## 商用判定に向けた残課題

- UFD 単体では本コホートの生成画像を依然検出できない
  (tuning 91 群中 0 群、evaluation 24 群中 0 群)。
  較正 `unmet` のため最終評価の判定自体が未適用であり、検出率の数値は
  「測れなかった」の記録であることに変わりはない。
- 実写が 105 群 (evaluation は 22 群) で、要求 1,500 群・目標 3,000 群に
  遠く届かない。仮に誤検知 0 件でも片側 95% 上限は 0/22 群で約 12.7% であり、
  採用基準の 0.1% 以下を証拠立てられない (#48 から変化なし)。
- HEIC/HEIF 入力 0 件、部分編集 0 件のため、対応する充足条件は未検証
  (#48 から変化なし)。
- 次の選択肢は (a) UFD 以外の検出器 (Community Forensics など) の追加評価、
  (b) 実写コホートの大幅拡充、(c) 現行生成器に強い検出器への置き換え検討である。
  生成枚数の追加だけでは較正 unmet は解消しないことが本評価で確認された。

## 再現手順

```sh
uv run python scripts/generate_ai_pictures.py --manifest /tmp/detecter-issue50-manifest.tsv
uv run python -m detecter.cohort scan ai-picture \
  --output /tmp/detecter-issue50-inv-ai.jsonl --allow-missing-camera
# /tmp/detecter-issue50-inv-ai.jsonl をファイル名で /tmp/inv-gpt.jsonl と /tmp/inv-nb.jsonl に分割
uv run python -m detecter.cohort build \
  --manifest /tmp/detecter-issue50-cohort-manifest.json \
  --ledger /tmp/detecter-issue50-ledger.jsonl \
  --seed 20260924 --evaluation-fraction 0.2 \
  --report /tmp/detecter-issue50-build.json
# 実写 105 行の split を /tmp/detecter-issue48-ledger.jsonl の割当てに復元 (sha256 照合)
uv run python -m detecter.ufd_batch \
  --ledger /tmp/detecter-issue50-ledger-newonly.jsonl \
  --output /tmp/detecter-issue50-measurements-new.jsonl --device cpu
# 前回計測 159 件 (sha256 一致) と結合 → /tmp/detecter-issue50-measurements.jsonl
# tuning 行だけに絞った台帳・計測で較正
uv run python -m detecter.calibration \
  --ledger /tmp/detecter-issue50-tuning-ledger.jsonl \
  --measurements /tmp/detecter-issue50-tuning-measurements.jsonl \
  --split tuning --output /tmp/detecter-issue50-decision-config.json
uv run python -m detecter.evaluation \
  --ledger /tmp/detecter-issue50-ledger.jsonl \
  --measurements /tmp/detecter-issue50-measurements.jsonl \
  --decisions /tmp/detecter-issue50-eval-decisions.jsonl \
  --unit source_group --split evaluation \
  --output /tmp/detecter-issue50-evaluation.json
uv run detecter evaluate-pipeline \
  --ledger /tmp/detecter-issue50-ledger.jsonl \
  --decision-config /tmp/detecter-issue50-decision-config.json \
  --measurements /tmp/detecter-issue50-measurements.jsonl \
  --required-generator "GPT Image 2:10" \
  --required-generator "Nano Banana:10" \
  --output /tmp/detecter-issue50-pipeline.json
```

evaluation 用の判定記録は `detecter.cli.apply_decision` で
計測へ判定設定を適用して作成した
(`evaluate-pipeline` が判定記録なしで実行する自動生成と同等)。
前回計測の再利用は sha256 照合で行い、`image_id` は新台帳に付け替えた
(結合後に台帳との `image_id`/`sha256` 対応を全件検証済み)。
