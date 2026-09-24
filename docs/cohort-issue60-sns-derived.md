# Issue #60: SNS相当加工 (EXIF除去・縮小・再圧縮) での再評価 (2026-09-24)

Issue #52 の生画像比較 (EXIFあり実写105群 vs 未加工生成115群) が実運用分布
(EXIFなし・再圧縮・リサイズ済み) を反映していない疑いに対する再評価である。
実写側を iphone-picture 全体 (1,995枚) へ広げ、実写・生成の両方にSNS相当加工を
施して UFD / Community Forensics / CuRe を同一条件で計測した。

結論: SNS加工で検出率は上がらず、下がる。3検出器とも較正 `unmet` のままであり、
商用判定 (`evaluate-pipeline: not_met`) には依然届かない。

## 1. 実写コホートの設計変更: 選択肢 (a) を採用

`cohort scan --allow-missing-camera` では目録に入るが、`build` の `real` ラベルが
`camera` (EXIF Make/Model) 必須のため PNG 1,501 枚が台帳に入らない。
Issue 本文の選択肢のうち、最小差分の (a)
「`build` に camera なし real を許すオプションを追加」を実装した
(`src/detecter/cohort.py`: `_source_rows` / `build_ledger` に
`allow_missing_camera` 引数、`build --allow-missing-camera` フラグ、
manifest の source entry ごとの `allow_missing_camera` に対応。
camera 欠落行は `camera: "unknown"` で台帳に入り、件数は `skipped.camera_unknown`
に数える。既定は従来どおり除外)。
`ledger.py` の検証は `camera` を必須としていないため変更不要だった。

スクリーンショットを `real` に混ぜる正当性の整理:

- SNS実運用の入力は「EXIFなし・再圧縮・リサイズ済み」であり、出所がカメラ撮影か
  スクリーンショットかは区別できない。加工後の分布としては同一条件に置ける。
- ただし「他人のSNS画像」とは厳密に同一ではない (所有者の私物デバイス由来、
  被写体・アプリ加工の偏りあり)。制約として明記する。
- `camera: "unknown"` で出所不明を区別可能にし、`coverage_report` の
  `camera_diversity` は `unknown` を1機種として数える (水増しにならないよう
  内訳 `cameras` を併記する)。
- (b) 案 (EXIFあり105枚のまま) は実写不足 (採用基準 0.1% の証拠立て不可) が
  残るだけで、SNS分布への接近には寄与しないため不採用とした。

## 2. コホート構築 (715群: 実写600 + 生成115)

- 目録: `iphone-picture` 全量 1,995行 (PNG 1,501 / JPEG 490 / WEBP 4、
  EXIF Make/Model あり105枚) を `--allow-missing-camera` で取得。
- サンプリング (コスト抑制、決定論的): sha256順でEXIFあり105枚を全採用 +
  EXIFなし1,890枚から等間隔 (stride 3.82) で495枚 → 実写600行。
  生成は115枚全採用 (GPT Image 2: 58 / Nano Banana: 57)。
  perceptual hash の重複により 715行 → 701群 (実写586群 / 生成115群)。
- 分割: `seed 20260924 / evaluation-fraction 0.2` で自動分割後、
  #50台帳と sha256 照合で重複220行の split を復元 (4行のみずれを修正)。
  最終 tuning 569群 (実写478行・生成93行→91群)、evaluation 146行
  (実写122行→121群・生成24行→24群: GPT 13 / NB 11)。
- `build` 報告: 実写 `skipped: {camera_unknown: 495}`、生成の重複なし。

## 3. SNS相当加工 (縮小1024 → JPEG品質75 の2段階)

`derive_jpeg` は品質変更と縮小を独立条件として扱い、結合条件を持たない。
コード変更なしで結合を再現するため2段階で実行した
(中間PNGは可逆のため「縮小→JPEG再圧縮」と等価):

```sh
uv run python -m detecter.derive_jpeg --ledger /tmp/detecter-issue60-base-ledger.jsonl \
  --qualities '' --long-sides 1024 --output /tmp/detecter-issue60/step1-resize1024.jsonl
uv run python -m detecter.derive_jpeg --ledger /tmp/detecter-issue60/step1-resize1024.jsonl \
  --qualities 75 --long-sides '' --output /tmp/detecter-issue60/sns-q75.jsonl
```

- 出力715行 (`history` 2件: resize→jpeg、`source_group`/label/split 継承、
  `ledger validate` 通過)。
- 検証 (抜き打ち10枚): 全件 JPEG・長辺1024以下・EXIFなし。
- 由来: 台帳行が増えるが `source_image_id` / `source_sha256` で元画像に結ぶ
  (Issue のメモどおり)。

## 4. 計測

```sh
uv run --extra community-forensics --extra cure \
  python -m detecter.comparison community-forensics ufd cure \
  --ledger /tmp/detecter-issue60/sns-q75.jsonl \
  --output /tmp/detecter-issue60/comparison.jsonl
```

- 2,145行 (715画像 × 3検出器)、全件 `ok`。

## 5. 較正 (tuning、誤検知0の動作点、群単位)

SNS全量 (tuning 569群: 実写465群・生成91群):

| 検出器 | status | しきい値 | 実写誤検知 | 生成検出 |
| --- | --- | --- | --- | --- |
| Community Forensics | `unmet` | -0.5593 (logit) | 0/465群 | 1/91群 (1.1%、NBのみ) |
| CuRe | `unmet` | 0.9999 | 0/465群 | 0/91群 (0.0%) |
| UFD | `unmet` | 0.9936 | 0/465群 | 0/91群 (0.0%) |

効果の切り分けとして、#50と同一220画像のSNS加工版だけに絞った較正
(tuning 174群、splitは#50と同一) も行った:

| 検出器 | 生 #52 (105実写) | SNS-220 (同一画像) | SNS-715 (実写拡大) |
| --- | --- | --- | --- |
| Community Forensics | 28/91群 (GPT 5・NB 23) | 10/91群 (GPT 2・NB 8) | 1/91群 (NB 1) |
| CuRe | 13/91群 (GPT 5・NB 8) | 0/91群 | 0/91群 |
| UFD | 0/91群 | 0/91群 | 0/91群 |

- SNS加工自体で検出が大幅に減る (CF 28→10、CuRe 13→0)。
- 実写拡大 (スクリーンショット混入) でさらに減る (CF 10→1)。
  スクリーンショット実写のスコアがEXIF写真より偽側に寄り、
  実写最大 (CF: -4.18 → -0.59) がしきい値を押し上げた。

スコア分布 (tuning、群単位):

| 検出器 | 実写 平均/最大 | GPT Image 2 平均/最大 | Nano Banana 平均/最大 |
| --- | --- | --- | --- |
| CF (logit) SNS | -9.59 / -0.59 | -8.20 / -2.08 | -7.13 / -0.56 |
| CF (logit) 生#52 | -9.80 / -0.54 | -4.27 / 8.92 | -0.70 / 9.77 |
| CuRe SNS | 0.053 / 0.9999 | 0.245 / 0.9992 | 0.517 / 0.9998 |
| CuRe 生#52 | 0.053 / 0.986 | 0.267 / 1.000 | 0.530 / 1.000 |
| UFD SNS | 0.063 / 0.994 | 0.067 / 0.681 | 0.039 / 0.496 |
| UFD 生#52 | 0.335 / 0.991 | 0.104 / 0.932 | 0.028 / 0.275 |

- CF は生成側の高スコア帯が崩壊 (NB最大 9.77 → -0.56) し、実写分布に沈んだ。
- CuRe は平均構造は保たれるが実写最大 (0.9999) が生成最大 (0.9998) を上回り、
  誤検知0点では1件も拾えない。
- UFD はSNS下でも転倒構造のまま (実写平均が生成を上回る) で全面未検出。

## 6. ORアンサンブル・最終評価

- OR (exactしきい値、`>=`): tuning 1/91群 (CFの1件のみ。CuRe・UFDは発火なし)。
- evaluation への参考適用 (正式値ではない): 実写誤検知 0/121群・生成検出 1/24群
  (NB 1件。tuning FP0は汎化したが検出も1件のみ)。
- 正式手順: 判定記録146件は全件 `inconclusive` (`config_invalid`、較正 `unmet`
  のため)。`evaluation` は実写誤検知率 `not_measured`・生成検出 0/24相当、
  `evaluate-pipeline` は3検出器とも `status: not_met`、
  未検証理由は `decision_config_invalid` のみ
  (生成器カバレッジ GPT 13 / NB 11群で `met`)。#52と同一構図である。

## 7. 結論

- SNS加工で検出率は上がらず、下がった。CF 30.8%→1.1%、CuRe 14.3%→0%、
  UFD 0%→0% (tuning、誤検知0点)。ORでも1/91群にとどまる。
- 要因は二重で、(1) 再圧縮・縮小が生成痕跡の信号を潰す効果と、
  (2) スクリーンショット混入の実写拡大が実写最大を押し上げ、FP0動作点を
  引き上げた効果が重なった。切り分け数値は §5 の3列比較を参照。
- 実写は586群まで増えたが、目標 (誤検知0.1%以下の証拠立て) には桁が足りない。
  SNS条件での採用基準到達には、検出器の更新と実写のさらなる増強の両方が必要。
- 本 issue のコード変更は `cohort build --allow-missing-camera` の最小差分のみ
  (テスト2件追加)。`derive_jpeg` の結合条件化は行わず2段階実行で代替した。

## 成果物 (いずれも `/tmp`、リポジトリには含めない)

- `/tmp/detecter-issue60-inv-real-all.jsonl` (1,995行)、`-inv-real-sample.jsonl` (600行)、
  `-inv-gpt.jsonl` (58行)、`-inv-nb.jsonl` (57行)、`-manifest.json`
- `/tmp/detecter-issue60-base-ledger.jsonl` (715行)、`-build.json`
- `/tmp/detecter-issue60/{step1-resize1024,sns-q75}.jsonl` + `.conditions.jsonl` + `.images/`
- `/tmp/detecter-issue60/comparison.jsonl` (2,145行、全件 `ok`)
- `/tmp/detecter-issue60/tuning-ledger.jsonl`、
  `{cf,ufd,cure}-{measurements,tuning-measurements}.jsonl`
- `/tmp/detecter-issue60/{cf,ufd,cure}-{decision-config,eval-decisions}.jsonl`、
  `-evaluation.json`、`-pipeline.json` (`not_met`)

## 再現手順

```sh
uv run python -m detecter.cohort scan iphone-picture \
  --output /tmp/detecter-issue60-inv-real-all.jsonl --allow-missing-camera
# → sha256順でEXIFあり全件 + EXIFなし等間隔495件を -inv-real-sample.jsonl に抽出
uv run python -m detecter.cohort build \
  --manifest /tmp/detecter-issue60-manifest.json \
  --ledger /tmp/detecter-issue60-base-ledger.jsonl \
  --seed 20260924 --evaluation-fraction 0.2 --allow-missing-camera \
  --report /tmp/detecter-issue60-build.json
# → #50台帳とsha256照合で重複220行のsplitを復元
uv run python -m detecter.derive_jpeg --ledger /tmp/detecter-issue60-base-ledger.jsonl \
  --qualities '' --long-sides 1024 --output /tmp/detecter-issue60/step1-resize1024.jsonl
uv run python -m detecter.derive_jpeg --ledger /tmp/detecter-issue60/step1-resize1024.jsonl \
  --qualities 75 --long-sides '' --output /tmp/detecter-issue60/sns-q75.jsonl
uv run --extra community-forensics --extra cure \
  python -m detecter.comparison community-forensics ufd cure \
  --ledger /tmp/detecter-issue60/sns-q75.jsonl \
  --output /tmp/detecter-issue60/comparison.jsonl
# 検出器別・tuning分割の抽出は image_id 突合せで行う (#52 と同方式)
uv run python -m detecter.calibration \
  --ledger /tmp/detecter-issue60/tuning-ledger.jsonl \
  --measurements /tmp/detecter-issue60/cf-tuning-measurements.jsonl \
  --split tuning --output /tmp/detecter-issue60/cf-decision-config.json
# evaluation / evaluate-pipeline は docs/cohort-issue52-comparison.md の再現手順に準ずる
```
