# Issue #48 ベースライン評価結果 (2026-09-24)

`ai-picture` / `iphone-picture` 評価コホートで `cohort build` →
`ufd_batch` → `calibration` → `evaluation` → `evaluate-pipeline` を
通した現状のベースライン記録である。画像本体はリポジトリに入れず、
台帳・計測・判定は `/tmp/detecter-issue48-*` に保存した。

## 評価スナップショット

- 実写: `/tmp/detecter-real-inventory-all.jsonl` (1,995 行: PNG 1,501、
  JPEG 490、WEBP 4。EXIF Make/Model ありは 105 枚のみ)
- 生成画像: 評価時点の `ai-picture` 54 枚 (GPT Image 2 系 27 枚、
  Nano Banana 系 27 枚。各 `*-test01.png` を含む)
- 最終 `cohort scan` 後に `ai-picture` は 65 ファイルまで増加した。
  差分 11 枚は本評価の対象外であり、次回評価で取り込む

## 台帳構成

マニフェストは `/tmp/detecter-cohort-manifest.json`
(実写 `minimum_real_groups: 1500`、生成器各 10 群要求、Midjourney 対象外)。
`--seed 20260924 --evaluation-fraction 0.2` で自動分割した。
生成画像の `split` 固定は使わず、tuning 側にも生成群が残る分割を選んだ
(全件 evaluation 固定にすると tuning に生成群が無くなり
`calibrate_records` が拒否するため)。

| ラベル | tuning | evaluation |
| --- | --- | --- |
| 実写 | 83 群 | 22 群 |
| 全体生成 | 44 群 | 10 群 (GPT Image 2: 4 群、Nano Banana: 6 群) |

台帳: `/tmp/detecter-issue48-ledger.jsonl` (159 行)、
内訳報告: `/tmp/detecter-issue48-build.json`。
実写は 1,995 行中 105 行のみ採用 (camera 不足で 1,846 行除外、重複 44 行除外)。
`real_source_groups`、`generator_groups`、`heif_inputs` などは不足
(`camera_diversity`、`edited_groups`、`outside_repository` は達成)。

## 計測

`uv run python -m detecter.ufd_batch --ledger <台帳> --output <計測>.jsonl --device cpu`
で 159 件全件 `ok` (失敗 0)。モデル条件は全行同一
(`model: ufd`、`preprocessing_version: ufd-rgb-exif-center224-clip-normalize-v2`)。
計測: `/tmp/detecter-issue48-measurements.jsonl`。

## 較正 (tuning 127 群)

tuning 行だけの台帳 (`/tmp/detecter-issue48-tuning-ledger.jsonl`) と
計測 (`/tmp/detecter-issue48-tuning-measurements.jsonl`) で
`python -m detecter.calibration --split tuning` を実行した。
結果は `status: unmet`、しきい値 0.9914、
実写誤検知 0/83 群、全体生成検出 0/44 群
(設定: `/tmp/detecter-issue48-decision-config.json`)。

UFD スコアは実写と生成画像で大きく重なり、分離できない。
tuning 群単位 (実写は群内最大、生成は群内最小) のしきい値別成績:

| しきい値 | 実写誤検知 | 生成検出 |
| --- | --- | --- |
| 0.9 | 9/83 (10.8%) | 0/44 (0.0%) |
| 0.5 | 29/83 (34.9%) | 1/44 (2.3%) |
| 0.1 | 41/83 (49.4%) | 5/44 (11.4%) |
| 0.01 | 64/83 (77.1%) | 22/44 (50.0%) |

実写の上位スコア (0.99 など) が生成画像の上位 (0.55) を上回り、
誤検知率 0.1% 以下と検出率 90% 以上を同時に満たす候補は存在しない。
UFD (旧世代生成器で学習) は `gpt_image_2` / `nano_banana` の
スマートフォン風スナップショットを実写より低く採点する。

## 最終評価 (evaluation 32 群)

未達設定は判定に適用しない仕様のため、evaluation 32 件の判定記録
(`/tmp/detecter-issue48-eval-decisions.jsonl`) は全件 `inconclusive`
(理由 `config_invalid`)。`detecter.evaluation --unit source_group
--split evaluation` の結果 (`/tmp/detecter-issue48-evaluation.json`):

| 指標 | 分子/分母 | 状態 |
| --- | --- | --- |
| 実写誤検知率 | 判定不能 (分母 0、22 群を `config_invalid` で除外) | `not_measured` |
| 全体生成検出率 | 0/10 | `measured` (0.0) |
| 部分編集検出率 | 対象なし | `insufficient_data` |
| 実行失敗率 | 0/32 | `measured` |
| 保留率 | 32/32 | `measured` |

生成器別の検出率 (Clopper-Pearson 片側 95% 下限):

| 生成器 | 検出 | 点推定 | 95% 下限 |
| --- | --- | --- | --- |
| GPT Image 2 | 0/4 群 | 0.0 | 0.0 |
| Nano Banana | 0/6 群 | 0.0 | 0.0 |
| 全体生成 | 0/10 群 | 0.0 | 0.0 |

`detecter evaluate-pipeline` の結果
(`/tmp/detecter-issue48-pipeline.json`) は `status: not_met`、
未検証理由は `generator_group_insufficient:GPT Image 2`、
`generator_group_insufficient:Nano Banana`、`decision_config_invalid`。

## 商用判定の根拠として不十分な点

- 実写が 105 群 (evaluation は 22 群) で、要求 1,500 群・目標 3,000 群に
  遠く届かない。仮に誤検知 0 件でも片側 95% 上限は 0/22 群で約 12.7%、
  0/105 群でも約 2.8% であり、採用基準の 0.1% 以下を証拠立てられない。
- 生成器の evaluation 群が各 10 群の要求に満たない
  (GPT Image 2: 4 群、Nano Banana: 6 群)。現行 54 枚では seed を変えても
  10 群ずつは確保できず、生成枚数の追加が必要。
- HEIC/HEIF 入力 0 件、部分編集 0 件のため、対応する充足条件は未検証。
- UFD 単体では本コホートの生成画像を検出できない
  (tuning で検出 0/44 群)。較正が `unmet` のため最終評価の判定自体が
  未適用であり、検出率の数値は「測れなかった」の記録である。

## PNG スクリーンショットを real として扱えない設計上の問題

- `cohort scan` 既定では撮影機器不明の 1,890 枚を除外する。
  `--allow-missing-camera` で目録に入れても、`build` の `real` ラベルが
  `camera` (EXIF Make/Model) 必須のため、結局 PNG 1,501 枚は台帳に入らない。
- PNG スクリーンショットは「iPhone で撮った写真」ではないため、
  そのまま `real` へ混ぜると実写の定義が崩れる。
  対応案は (a) カメラ EXIF あり画像のみを実写対象と明示する、
  (b) スクリーンショット由来を区別する出所ラベルや
  `--include-screenshot` 相当の取込み方を `cohort` に追加する、のいずれか。
  本評価は (a) の立場で 105 群だけを実写とした。
- 実写 JPEG 490 枚中 EXIF ありは 105 枚 (約 21%) にとどまる。
  SNS 転送などで EXIF が剥落した画像の扱いも別途方針が必要。

## 再現手順

```sh
uv run python -m detecter.cohort scan ai-picture \
  --output /tmp/inv-ai.jsonl --allow-missing-camera
# /tmp/inv-ai.jsonl をファイル名で /tmp/inv-gpt.jsonl と /tmp/inv-nb.jsonl に分割
uv run python -m detecter.cohort build \
  --manifest /tmp/detecter-cohort-manifest.json \
  --ledger /tmp/detecter-issue48-ledger.jsonl \
  --seed 20260924 --evaluation-fraction 0.2 \
  --report /tmp/detecter-issue48-build.json
uv run python -m detecter.ufd_batch \
  --ledger /tmp/detecter-issue48-ledger.jsonl \
  --output /tmp/detecter-issue48-measurements.jsonl --device cpu
# tuning 行だけに絞った台帳・計測で較正
uv run python -m detecter.calibration \
  --ledger /tmp/detecter-issue48-tuning-ledger.jsonl \
  --measurements /tmp/detecter-issue48-tuning-measurements.jsonl \
  --split tuning --output /tmp/detecter-issue48-decision-config.json
uv run python -m detecter.evaluation \
  --ledger /tmp/detecter-issue48-ledger.jsonl \
  --measurements /tmp/detecter-issue48-measurements.jsonl \
  --decisions /tmp/detecter-issue48-eval-decisions.jsonl \
  --unit source_group --split evaluation \
  --output /tmp/detecter-issue48-evaluation.json
uv run detecter evaluate-pipeline \
  --ledger /tmp/detecter-issue48-ledger.jsonl \
  --decision-config /tmp/detecter-issue48-decision-config.json \
  --measurements /tmp/detecter-issue48-measurements.jsonl \
  --required-generator "GPT Image 2:10" \
  --required-generator "Nano Banana:10" \
  --output /tmp/detecter-issue48-pipeline.json
```

evaluation 用の判定記録は `detecter.cli.apply_decision` で
計測へ判定設定を適用して作成した
(`evaluate-pipeline` が判定記録なしで実行する自動生成と同等)。
