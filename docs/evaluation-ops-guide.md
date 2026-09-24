# 評価運用ガイド (Issues #48 / #50 / #52 / #54 / #56 横断まとめ)

3 検出器 (UFD / Community Forensics / CuRe) のアンサンブルでも、
tuning 誤検知 0 の動作点での生成検出は 38/91 群 (41.8%) にとどまり、
目標 (実写誤検知率 0.1% 以下かつ生成検出率 90% 以上) には遠く及ばない。
現行の評価データは商用判定の根拠として不足が確定したため、
既知の限界と再現手順をここに整理する。

関連記録:

- `docs/cohort-baseline-issue48.md` (ベースライン、UFD 単体)
- `docs/cohort-issue50-scale.md` (生成 115 枚への増量)
- `docs/cohort-issue52-comparison.md` (3 検出器比較)
- `docs/cohort-issue54-cf-calibrated.md` (CF logit しきい値の管道対応)
- `docs/cohort-issue56-ensemble.md` (OR / 線形統合)

画像本体・台帳・計測はリポジトリに入れない。
評価成果物は `/tmp/detecter-issue*-*` に置く運用である。

## 1. 結論: 商用判定は現時点で未達

- `evaluate-pipeline` の `status` は #48・#50・#52・#54 を通じて一貫して `not_met`。
  未検証理由は最終的に `decision_config_invalid` のみ
  (生成器カバレッジは #50 で解消済み)。
- 較正 (`calibration`) の `status` は UFD / CF / CuRe いずれも `unmet`。
  未達設定は判定に適用しない仕様のため、evaluation の判定記録は全件
  `inconclusive`、実写誤検知率は `not_measured`、全体生成検出率は `0/24` のままである。
  数値の意味は「測れなかった」の記録であり、検出率 0% の確定ではない。
- OR アンサンブル (CF+CuRe、UFD は寄与なし) で tuning 38/91 群 (41.8%) まで
  改善するが、較正目標には届かず `status` は `unmet` のままである
  (詳細は §6)。

## 2. 実写コホートの作り方と限界: iphone-picture の EXIF 事情

- 実写 inventory は 1,995 行 (PNG 1,501、JPEG 490、WEBP 4)。
  EXIF Make/Model ありは 105 枚のみ (実写 JPEG 490 枚中の約 21%)。
- `cohort scan` 既定では撮影機器不明の 1,890 枚を除外する。
  `--allow-missing-camera` で目録に入れても、`build` の `real` ラベルが
  `camera` (EXIF Make/Model) 必須のため、PNG 1,501 枚は台帳に入らない。
- PNG スクリーンショットは「iPhone で撮った写真」ではないため、
  そのまま `real` へ混ぜると実写の定義が崩れる。
  本評価は「カメラ EXIF あり画像のみを実写対象とする」立場で 105 群だけを実写とした。
  対応案は (a) 現行どおり EXIF ありのみを実写とするか、
  (b) スクリーンショット由来を区別する出所ラベルや
  `--include-screenshot` 相当の取込み方を `cohort` に追加するか、のいずれか。
- 実写 105 群 (evaluation は 22 群) は要求 1,500 群・目標 3,000 群に遠く届かない。
  仮に誤検知 0 件でも片側 95% 上限 (Clopper-Pearson) は
  0/22 群で約 12.7%、0/105 群でも約 2.8% であり、
  採用基準の 0.1% 以下を証拠立てられない。
- SNS 転送などで EXIF が剥落した画像の扱いは別途方針が必要。
- 実写 83/22 群の tuning/evaluation 割当ては #48 で確定し、
  #50 では sha256 照合で同一割当てに復元した。
  行数増加による自動分割のカット位置移動をそのままにすると実写割当てがずれるため、
  増量時は割当て復元を忘れないこと。

## 3. 生成画像の増量手順: ai-picture

増量は `scripts/generate_ai_pictures.py` + TSV manifest + higgsfield CLI で行う。
既存ファイルはスキップされ、成功分は `receipts/<stem>.json` にジョブレシートが残る。

```sh
uv run python scripts/generate_ai_pictures.py --manifest /tmp/detecter-issue50-manifest.tsv
```

- TSV は 1 行 1 画像 (`filename`, `model`, `prompt`, `aspect_ratio`, `quality` 列)。
  #50 では 50 行 (GPT Image 2 系 25 枚 `gpt-image-2-033.png` 〜 `-057.png`、
  Nano Banana 系 25 枚 `nano-banana-032.png` 〜 `-056.png`) を失敗 0 件で実行した。
- モデル指定は `gpt_image_2` / `nano_banana`。
  `gpt_image_*` のみ `--quality low --resolution 1k` が付く。
  プロンプトは日本の日常スマホ写真 (食事、街、室内、乗り物、季節の風景、手元アップなど) で多様化し、
  アスペクト比は 4:3 中心に 1:1 / 3:4 / 16:9 を混在させた。
- 結果: `ai-picture` は 65 枚 → 115 枚
  (GPT Image 2 系 58 枚 = 連番 57 + テスト 1、
  Nano Banana 系 57 枚 = 連番 56 + テスト 1)。
- `cohort scan` は `--allow-missing-camera` で 115 行の inventory を作り、
  ファイル名で GPT 用・NB 用に分割して `build` に渡す。
  #50 の生成器別 evaluation 群は GPT Image 2: 13 群、Nano Banana: 11 群となり、
  各 10 群の要求 (`generator_groups: met`) を充足した。
  tuning 側にも各 40 群以上が残るため `calibrate_records` の生成群要件も満たす。
- 注意: プロンプト多様化による検出されやすさの変化は見られなかった
  (新規 61 枚の平均 UFD スコア 0.08 vs 既存 54 枚の平均 0.07)。
  生成枚数の追加だけでは較正 `unmet` は解消しないことが #50 で確認済みである。

## 4. 標準の実行手順: scan → build → 計測 → 較正 → 評価 → pipeline

以下は #50 時点の全体像である (#48 の詳細コマンドは
`docs/cohort-baseline-issue48.md` の再現手順を参照)。

```sh
# 1. 生成画像の用意 (§3)
uv run python scripts/generate_ai_pictures.py --manifest /tmp/detecter-issue50-manifest.tsv

# 2. 目録化
uv run python -m detecter.cohort scan ai-picture \
  --output /tmp/detecter-issue50-inv-ai.jsonl --allow-missing-camera
# → ファイル名で /tmp/inv-gpt.jsonl と /tmp/inv-nb.jsonl に分割

# 3. 台帳化 (tuning/evaluation 自動分割)
uv run python -m detecter.cohort build \
  --manifest /tmp/detecter-issue50-cohort-manifest.json \
  --ledger /tmp/detecter-issue50-ledger.jsonl \
  --seed 20260924 --evaluation-fraction 0.2 \
  --report /tmp/detecter-issue50-build.json
# → 実写 105 行の split は sha256 照合で #48 台帳の割当てに復元する

# 4a. 単一検出器の計測 (UFD)
uv run python -m detecter.ufd_batch \
  --ledger /tmp/detecter-issue50-ledger.jsonl \
  --output /tmp/detecter-issue50-measurements.jsonl --device cpu

# 4b. 複数検出器の計測 (比較用)
uv run --extra community-forensics --extra cure \
  python -m detecter.comparison community-forensics ufd cure \
  --ledger /tmp/detecter-issue50-ledger.jsonl \
  --output /tmp/detecter-issue52-comparison.jsonl

# 5. 較正 (tuning 行だけに絞った台帳・計測で実行)
uv run python -m detecter.calibration \
  --ledger /tmp/detecter-issue50-tuning-ledger.jsonl \
  --measurements /tmp/detecter-issue50-tuning-measurements.jsonl \
  --split tuning --output /tmp/detecter-issue50-decision-config.json

# 6. 最終評価
uv run python -m detecter.evaluation \
  --ledger /tmp/detecter-issue50-ledger.jsonl \
  --measurements /tmp/detecter-issue50-measurements.jsonl \
  --decisions /tmp/detecter-issue50-eval-decisions.jsonl \
  --unit source_group --split evaluation \
  --output /tmp/detecter-issue50-evaluation.json

# 7. 採用可否
uv run detecter evaluate-pipeline \
  --ledger /tmp/detecter-issue50-ledger.jsonl \
  --decision-config /tmp/detecter-issue50-decision-config.json \
  --measurements /tmp/detecter-issue50-measurements.jsonl \
  --required-generator "GPT Image 2:10" \
  --required-generator "Nano Banana:10" \
  --output /tmp/detecter-issue50-pipeline.json
```

補足:

- 計測の再利用は sha256 照合で行い、`image_id` は新台帳に付け替える
  (結合後に台帳との対応を全件検証する。#50 の前回分 159 件再利用と同方式)。
- UFD 再計測 220 件は #50 計測と `raw_score` が全件一致した
  (モデル・重み・前処理条件が同一であることの傍証)。
- evaluation 用の判定記録は `detecter.cli.apply_decision` で計測へ判定設定を
  適用して作成する (`evaluate-pipeline` の自動生成と同等)。
- CF / CuRe の較正・評価は `comparison` 出力から検出器ごとに行を抽出し、
  tuning ledger と image_id 突合せで行う。CF / CuRe の再現手順は
  `docs/cohort-issue52-comparison.md` を参照。
- `comparison` の依存は `uv sync --extra community-forensics --extra cure` で用意し、
  重みは共有キャッシュ (`~/.cache/detecter/community-forensics-384`, `cure`)
  から自動取得される。
- CF の較正しきい値は logit のため、そのままでは旧 `apply_decision` の
  `[0, 1]` チェックに抵触した。#54 で当該チェックを削除し、
  有限性検証を `validate_config` に一本化した。
  安定 sigmoid 派生計測でも順序保存を確認のうえ同一結果 (28/91 群) を再現した。

## 5. 各検出器の得意 / 不得意 (同一コホート 220 群での比較)

tuning 174 群 (実写 83・生成 91) での誤検知 0 の動作点の成績:

| 検出器 | status | しきい値 | 実写誤検知 | 生成検出 |
| --- | --- | --- | --- | --- |
| Community Forensics | `unmet` | -0.1506 (logit、sigmoid 換算 0.4624) | 0/83 群 | 28/91 群 (30.8%) |
| CuRe | `unmet` | 0.9882 | 0/83 群 | 13/91 群 (14.3%) |
| UFD | `unmet` | 0.9914 | 0/83 群 | 0/91 群 (0.0%) |

生成器別の内訳 (tuning 群単位):

| 検出器 | GPT Image 2 | Nano Banana |
| --- | --- | --- |
| Community Forensics | 5/45 群 (11.1%) | 23/46 群 (50.0%) |
| CuRe | 5/45 群 (11.1%) | 8/46 群 (17.4%) |
| UFD | 0/45 群 | 0/46 群 |

- UFD: 本コホートでは全面未検出。実写の平均スコア (0.335) が
  生成画像 (GPT 0.104、NB 0.028) を上回る転倒構造のため、しきい値方式では分離不能。
  旧世代生成器で学習した UFD は `gpt_image_2` / `nano_banana` の
  スマートフォン風スナップショットを実写より低く採点する。
- CF: Nano Banana に強い (tuning 23/46 群、evaluation 参考値 6/11 群) 一方、
  GPT Image 2 は 5/45 群にとどまる。実写と生成の平均が最も離れており
  (実写 -9.80 に対し NB -0.70)、生成上位と実写最大の間に余白があるが、
  生成下位の半数以上が実写分布に沈むため 90% 検出には届かない。
- CuRe: 生成上位 5 群が 0.999 以上に張り付く一方、実写最大も 0.986 と高く、
  しきい値を上げると検出が急減する (誤検知 0 点で 13/91 群)。
  GPT / NB とも 1 割台で、単体では弱い。
- いずれも誤検知率 0.1% 以下と検出率 90% 以上を同時に満たさず `unmet`。
  ただし誤検知 0 点での検出数は CF・CuRe が UFD を上回り、
  CF・CuRe の導入で初めて生成器ごとの得意不得意が見えた。

## 6. アンサンブル結果 (Issue #56)

OR (いずれか 1 検出器が超過なら陽性、しきい値は較正 decision-config の exact 値を `>=` 比較):

| 対象 | 実写誤検知 | 生成検出 | GPT Image 2 | Nano Banana |
| --- | --- | --- | --- | --- |
| OR (3 検出器) | 0/83 群 | 38/91 群 (41.8%) | 9/45 群 (20.0%) | 29/46 群 (63.0%) |
| CF 単体 | 0/83 群 | 28/91 群 (30.8%) | 5/45 群 | 23/46 群 |
| CuRe 単体 | 0/83 群 | 13/91 群 (14.3%) | 5/45 群 | 8/46 群 |
| UFD 単体 | 0/83 群 | 0/91 群 | 0/45 群 | 0/46 群 |

- OR の内訳: CF のみ 25 群、CuRe のみ 10 群、両方 3 群 (UFD は一度も発火しない)。
  CF に対する上積み +10 群は GPT 4 群・NB 6 群である。実質は CF+CuRe の OR である。
- 線形統合 (min-max 正規化 + 重み付き平均) に OR を超える安定した効果はない。
  無難な 1:1 平均 (34/91) は OR (38/91) を下回り、
  CF:CuRe = 2:1 の 43/91 は重み掃引の中で突出した上振れで evaluation で再現しない
  (9 vs 7 に縮小)。UFD を含む平均・正規化 max はいずれも CF 単体以下である。
- evaluation 群への参考適用 (正式な検出率ではない):
  OR で実写誤検知 2 群・生成検出 7 群 (GPT 1・NB 6)。
  tuning 誤検知 0 を evaluation に汎化できず、CF 単体と同じ 2 群の誤検知が出る。
  実写 83 群での FP0 保証は弱い。
- しきい値の丸めは禁止 (exact 値の保存と比較 `>=` が再現条件)。
  丸め値で厳密 `>` 比較すると CF 27・CuRe 12 になり、較正記録 (28・13) と一致しない。
- 融合後の `decision-config` を新設しても 38/91 のため `status: unmet` になり、
  正式適用はできない。よって detecter 側の本格実装 (新モジュール・設定拡張) は見送り、
  最小実装の検討に留めるのが妥当である (詳細は `docs/cohort-issue56-ensemble.md`)。

## 7. 商用判定に必要な残り条件

1. 実写数千群: 要求 1,500 群・目標 3,000 群に対し現状 105 群。
   誤検知 0.1% 以下の証拠立てには桁違いの実写増強が必要。
2. 生成器ごとの十分な evaluation 群: #50 で各 10 群の最低線は満たしたが
   (GPT 13 / NB 11 群)、検出率 90% の下限保証には各生成器でさらに十分な群が必要。
   現行の点推定 0/13・0/11 の 95% 上限は約 20〜24% であり、余白が大きい。
3. 部分編集 (edited) の追加: 現状 0 件のため `edited_groups` は未検証。
   全体生成検出率に混ぜず `edited_detection_rate` と履歴別内訳で報告する仕様である。
4. HEIC/HEIF の追加: 現状 0 件のため `heif_inputs` は未検証。
5. 検出器の更新: UFD は本コホートで全面未検出、CF は NB 偏重、CuRe は単体で弱い。
   より新しい生成器に対応したモデルの追加評価、または生成器ごとの検出器選択・統合の検討が必要。
   ただし線形統合の重み調整での改善主張は過適合のためできない (OR が現実的な上限)。
6. 判定管道の整備: CF logit 問題は #54 で解消済み (`threshold_invalid` の消滅)。
   今後 logit 系検出器を追加する場合は有限性のみを要求し、計測意味の変更は避けること。

## 8. よくある落とし穴

- 未達設定を evaluation に適用しても正式な検出率にはならない。
  `evaluation` は `not_measured` / `0/24`、`evaluate-pipeline` は `not_met` になるのが正常である。
  参考適用の数値は「情報値」として記録し、正式値と混同しないこと。
- 生成画像の `split` 固定は使わない。tuning 側に生成群が残らない分割では
  `calibrate_records` が拒否するため (#48)。
- `build` の実写割当ては増量時に sha256 照合で復元する (#50)。
- `calibration.py` の比較は `>=`、しきい値は decision-config の exact 値を使う (#56)。
- 成果物は `/tmp` に置き、リポジトリには含めない。
  symlink 類 (画像・receipts 等の外部参照) はコミットしない。
