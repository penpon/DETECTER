# Issue #64: 評価指標を TPR@FPR(1%, 0.1%)・群単位・画像種別集計へ切り替え (2026-09-25)

従来の評価 (正解率・誤検知0動作点での群検出数) に代わる共通土台として、
群 (`source_group`) 単位の TPR@FPR=1% / 0.1% と画像種別 (`image_kind`) ごとの
集計を `detecter.evaluation` に追加し、Issue #60/#62 の既存計測
(UFD / Community Forensics / CuRe / EFFORT) を再集計した。

結論: 現コホートの実写群数では FPR=0.1% が許容する FP は全条件で 0 件であり、
0.1% 動作点は従来の誤検知0動作点と一致する。種別集計により、実写の高スコア裾が
EXIF なしのスクリーンショット・保存画像 (kind=`unknown`) 側に集中していることが
定量的に確認できた。EXIF 確認済み実写 (kind=`photo`) のみを分母にした動作点では
検出率が大きく上がる (参考値。種別分離した運用が前提)。

## 1. 実装

### `tpr_at_fpr` ブロック (`src/detecter/evaluation.py`)

- スコアは群単位: 群内の派生画像スコアを実写は `max` (1枚でも超過すれば群FP)、
  生成・部分編集は `min` (全員が超過して初めて群検出) で集約する。
  判定集計の `any_positive_real; all_positive_generated_or_edited` と同じ規則であり、
  `calibration` の群スコア集約とも一致する。
- 実写群数 N に対して各 FPR が許容する FP 件数は `floor(N × FPR)` で、
  `allowed_false_positives` として各動作点に明記する。
- しきい値は「実写群スコアの (許容FP+1) 番目に大きい値の直上」
  (`math.nextafter`) とし、`raw_score >= threshold` で判定する。
  許容 FP 内で最も緩い (TPR を最大化する) 動作点である。
  計測できなかった実写群は分母から除き `unscored_real_groups` に数える。
  未計測メンバーを含む生成群は検出できないものとして分母に残す
  (`generated_detection_rate` が失敗・保留を分母に残すのと同じ方針)。
- `unknown` ラベルの群は実写側・生成側のいずれの分母にも入れない。
- 出力は `overall` と `by_image_kind` の2系統で、種別ごとに実写群・
  生成群・しきい値・FP件数・TPR を独立に計算する
  (種別内完結の動作点。混合運用のしきい値ではない点に注意)。

### `image_kind` 台帳フィールド (`src/detecter/cohort.py` / `ledger.py`)

- manifest の source entry に `image_kind` (任意文字列、省略時 `unknown`) を
  追加すると台帳行へ記録される。派生 (`derive_jpeg`)・分割 (`ledger split`) は
  既存の全フィールド継承でそのまま引き継ぐ。
- 台帳検証は任意文字列フィールドとして `generator`・`camera` と同じ規則で
  `image_kind` を検査する (`ledger.py`)。
- `breakdowns` の集計軸にも `image_kind` を追加した。

### 既存コホートへの種別付与 (再集計用)

Issue #60 台帳 (`sns-q75.jsonl`、715行) は `image_kind` を持たないため、
再集計用のコピーへ次の規則で付与した (元データは変更していない):

- `real` かつ `camera` が EXIF 確認済み → `photo` (105行)
- `real` かつ `camera: "unknown"` → `unknown` (495行)。
  スクリーンショットと保存画像の混合で、内容が写真かイラストかを画像ごとに
  検証していないため `photo` と主張しない (実測でアプリUI・保存写真が混在)。
- `generated` → `photo` (115行)。全115件の生成レシートのプロンプトが
  スマホ写真風であり、イラスト系生成は現コホートに存在しない
  (非AIイラスト群の追加は Issue #69 の範囲)。

## 2. 各 FPR が許容する FP 件数 (実写群数から)

| split | 実写群数 | FPR=1% が許容するFP | FPR=0.1% が許容するFP |
| --- | --- | --- | --- |
| tuning 全体 | 465 | 4件 | 0件 |
| tuning photo | 83 | 0件 | 0件 |
| tuning unknown | 382 | 3件 | 0件 |
| evaluation 全体 | 121 | 1件 | 0件 |
| evaluation photo | 22 | 0件 | 0件 |
| evaluation unknown | 99 | 0件 | 0件 |

現コホートでは FPR=0.1% は常に FP 0 許容 (= 従来の誤検知0動作点) になる。
0.1% 未満の運用を語るには実写群の増強 (Issue #69、目標2,995群) が前提になる。

## 3. 再集計結果 (群単位、SNS相当加工コホート)

### tuning (実写465群・生成91群)

| 検出器 | 範囲 | FPR=1%: しきい値 / FP / 生成検出 | FPR=0.1%: しきい値 / FP / 生成検出 |
| --- | --- | --- | --- |
| UFD | overall | 0.8982 / 4件 / 0/91群 (0.0%) | 0.9936 / 0件 / 0/91群 (0.0%) |
| | photo | 0.9936 / 0件 / 0/91群 (0.0%) | 0.9936 / 0件 / 0/91群 (0.0%) |
| | unknown | 0.8249 / 3件 / 生成群なし | 0.9331 / 0件 / 生成群なし |
| CF (logit) | overall | -2.2759 / 4件 / 3/91群 (3.3%) | -0.5899 / 0件 / 1/91群 (1.1%) |
| | photo | -4.1806 / 0件 / 10/91群 (11.0%) | -4.1806 / 0件 / 10/91群 (11.0%) |
| | unknown | -2.1252 / 3件 / 生成群なし | -0.5899 / 0件 / 生成群なし |
| CuRe | overall | 0.99760 / 4件 / 5/91群 (5.5%) | 0.999936 / 0件 / 0/91群 (0.0%) |
| | photo | 0.999936 / 0件 / 0/91群 (0.0%) | 0.999936 / 0件 / 0/91群 (0.0%) |
| | unknown | 0.99760 / 3件 / 生成群なし | 0.999547 / 0件 / 生成群なし |
| EFFORT | overall | 0.98990 / 4件 / 9/91群 (9.9%) | 0.99659 / 0件 / 2/91群 (2.2%) |
| | photo | 0.98076 / 0件 / 17/91群 (18.7%) | 0.98076 / 0件 / 17/91群 (18.7%) |
| | unknown | 0.99212 / 3件 / 生成群なし | 0.99659 / 0件 / 生成群なし |

### evaluation (実写121群・生成24群)

| 検出器 | 範囲 | FPR=1%: しきい値 / FP / 生成検出 | FPR=0.1%: しきい値 / FP / 生成検出 |
| --- | --- | --- | --- |
| UFD | overall | 0.8647 / 1件 / 0/24群 (0.0%) | 0.9372 / 0件 / 0/24群 (0.0%) |
| | photo | 0.8647 / 0件 / 0/24群 (0.0%) | 0.8647 / 0件 / 0/24群 (0.0%) |
| | unknown | 0.9372 / 0件 / 生成群なし | 0.9372 / 0件 / 生成群なし |
| CF (logit) | overall | -3.3951 / 1件 / 3/24群 (12.5%) | -2.1707 / 0件 / 3/24群 (12.5%) |
| | photo | -3.3951 / 0件 / 3/24群 (12.5%) | -3.3951 / 0件 / 3/24群 (12.5%) |
| | unknown | -2.1707 / 0件 / 生成群なし | -2.1707 / 0件 / 生成群なし |
| CuRe | overall | 0.99251 / 1件 / 2/24群 (8.3%) | 0.999864 / 0件 / 1/24群 (4.2%) |
| | photo | 0.9239 / 0件 / 6/24群 (25.0%) | 0.9239 / 0件 / 6/24群 (25.0%) |
| | unknown | 0.999864 / 0件 / 生成群なし | 0.999864 / 0件 / 生成群なし |
| EFFORT | overall | 0.98564 / 1件 / 3/24群 (12.5%) | 0.99196 / 0件 / 2/24群 (8.3%) |
| | photo | 0.98564 / 0件 / 3/24群 (12.5%) | 0.98564 / 0件 / 3/24群 (12.5%) |
| | unknown | 0.99196 / 0件 / 生成群なし | 0.99196 / 0件 / 生成群なし |

既存記録との照合: tuning の FP0 動作点 (CF 1/91、EFFORT 2/91) と
EFFORT の FPR≦1% 参考値 (9/91、しきい値 0.9899≈0.9902) は
`docs/cohort-issue60-sns-derived.md` / `docs/cohort-issue62-robust-detectors.md`
の値と一致する。

## 4. 観測

- **FPR=0.1% の FP 許容は全条件で 0件** (§2)。現状の実写群数では
  「誤検知0動作点でのTPR」がそのまま FPR=0.1% のTPRであり、
  0.1% 未満の保証は実写群の増強なしには出せない。
- **実写の高スコア裾は `unknown` 種に集中する。** CF の実写群最大は
  unknown -0.59 に対し photo は -4.18 であり、UFD でも
  unknown 0.933 / photo 0.8647 (evaluation) と同じ構図である。
  Issue #60 が「スクリーンショット実写が実写最大を押し上げた」と
  記録した効果を種別集計で直接確認できた。
- **種別内完結の `photo` 動作点では検出率が大きく上がる**
  (tuning: CF 1.1%→11.0%、EFFORT 2.2%→18.7%。evaluation: CuRe 4.2%→25.0%)。
  ただしこれは参考値である: 実写入力を種別で分離する仕組み
  (写真/非写真の事前分類) がなければ混合運用のしきい値は unknown 側の
  裾で決まり、`unknown` 種のFPは別分布として残る。
  生成側は全件 `photo` のため `photo` 種のTPR分母は全体と同じである。
- **部分編集 (`edited`) 群はコホートに存在しない**ため、
  `edited` のTPRは全条件で null (`groups: 0`) である。
- tuning と evaluation で検出される生成器の偏りは安定しない
  (EFFORT: tuning FP0 は GPT 2群、evaluation FP0 は NB 2群)。
  裾の動作点である以上、参考適用としても汎化は弱い (#62 と同じ結論)。

## 成果物

- `results/issue64-tpr-at-fpr.json`: 4検出器 × tuning/evaluation の
  再集計サマリ (しきい値・許容FP・実績FP・種別TPR)。
- 再集計の中間レポート (いずれも `/tmp`、リポジトリには含めない):
  `/tmp/detecter-issue64/sns-q75-kinded.jsonl` (image_kind 付与版台帳)、
  `/tmp/detecter-issue64/{cf,ufd,cure,effort}-{tuning,evaluation}.json`。

## 再現手順

```sh
# 既存台帳へ §1 の規則で image_kind を付与 (元データは変更しない)
#   real & camera != "unknown" → photo / real & camera == "unknown" → unknown
#   generated → photo
# → /tmp/detecter-issue64/sns-q75-kinded.jsonl
# 判定記録は較正 unmet で全件 inconclusive のため、スコア集計には空ファイルを渡す
: > /tmp/detecter-issue64/empty.jsonl
for det in cf ufd cure; do for split in tuning evaluation; do
  uv run python -m detecter.evaluation \
    --ledger /tmp/detecter-issue64/sns-q75-kinded.jsonl \
    --measurements /tmp/detecter-issue60/$det-measurements.jsonl \
    --decisions /tmp/detecter-issue64/empty.jsonl \
    --unit source_group --split $split \
    --output /tmp/detecter-issue64/$det-$split.json
done; done
for split in tuning evaluation; do
  uv run python -m detecter.evaluation \
    --ledger /tmp/detecter-issue64/sns-q75-kinded.jsonl \
    --measurements /tmp/detecter-issue62-effort.jsonl \
    --decisions /tmp/detecter-issue64/empty.jsonl \
    --unit source_group --split $split \
    --output /tmp/detecter-issue64/effort-$split.json
done
# 各レポートの .tpr_at_fpr.overall / .by_image_kind が本記録の表に対応する
```
