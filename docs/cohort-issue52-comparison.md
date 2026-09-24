# Issue #52 検出器比較: Community Forensics / CuRe / UFD (2026-09-24)

Issue #50 の台帳 (`/tmp/detecter-issue50-ledger.jsonl`、220 行:
実写 105 群 + GPT Image 2 58 群 + Nano Banana 57 群、tuning/evaluation 分割済み) に対し、
`detecter.comparison` で Community Forensics・UFD・CuRe の 3 検出器を同一画像群で計測し、
tuning 群で較正して検出率を比較した記録である。
UFD 単体では tuning 91 群・evaluation 24 群とも生成検出 0 件 (`unmet`) が確定済みであり、
本評価は「検出器の追加」が改善軸になるかを検証する。

## 計測

```sh
uv run --extra community-forensics --extra cure \
  python -m detecter.comparison community-forensics ufd cure \
  --ledger /tmp/detecter-issue50-ledger.jsonl \
  --output /tmp/detecter-issue52-comparison.jsonl
```

- 依存は `uv run --extra community-forensics python -c "import timm"`
  (`timm 1.0.15`) と `--extra cure` (`albumentations`) で確認済み。
  重みは共有キャッシュ (`~/.cache/detecter/community-forensics-384`,
  `cure`) から自動取得され、追加ダウンロード手順は不要だった。
- 出力 660 行 (220 画像 × 3 検出器)、全件 `ok`、終了コード 0。
  1 検出器の失敗もなく、失敗時の継続経路は今回未発動。
- UFD 再計測 220 件は Issue #50 の計測と `raw_score` が全件一致
  (差分 0 件)。モデル・重み・前処理条件が同一であることの傍証であり、
  以下の UFD 比較には今回の再計測値をそのまま用いた。
- 計測条件は全行同一モデル内でのみ比較可能
  (CF: `community-forensics-384` / logit、`cure` / 確率、`ufd` / 確率)。

## 較正 (tuning 174 群: 実写 83 群・生成 91 群)

比較出力から検出器ごとに行を抽出し、tuning  ledger
(`/tmp/detecter-issue50-tuning-ledger.jsonl`) と突き合わせて較正した
(UFD と同じ tuning 分割)。

| 検出器 | status | しきい値 | 実写誤検知 | 生成検出 |
| --- | --- | --- | --- | --- |
| Community Forensics | `unmet` | -0.1506 (logit) | 0/83 群 | 28/91 群 (30.8%) |
| CuRe | `unmet` | 0.9882 | 0/83 群 | 13/91 群 (14.3%) |
| UFD (#50) | `unmet` | 0.9914 | 0/83 群 | 0/91 群 (0.0%) |

- いずれも誤検知率 0.1% 以下と検出率 90% 以上を同時に満たさず `unmet`。
  ただし誤検知 0 の動作点での検出数は CF 28 群・CuRe 13 群と UFD (0 群) を
  上回り、CF は生成群の約 3 割を誤検知なしで拾える。
- 生成器別の内訳 (誤検知 0 の動作点、tuning 群単位):

| 検出器 | GPT Image 2 | Nano Banana |
| --- | --- | --- |
| Community Forensics | 5/45 群 (11.1%) | 23/46 群 (50.0%) |
| CuRe | 5/45 群 (11.1%) | 8/46 群 (17.4%) |
| UFD | 0/45 群 | 0/46 群 |

- CF・CuRe とも Nano Banana 側が検出されやすく、GPT Image 2 は両検出器でも
  1 割程度にとどまる。UFD は全面未検出のため生成器差自体が現れず、
  CF・CuRe の導入で初めて生成器ごとの得意不得意が見えた。

## スコア分布 (tuning 群・画像単位、参考)

| 検出器 | 実写 (83 枚) 平均 / 最大 | GPT Image 2 (45 枚) 平均 / 最大 | Nano Banana (46 枚) 平均 / 最大 |
| --- | --- | --- | --- |
| Community Forensics (logit) | -9.80 / -0.54 | -4.27 / 8.92 | -0.70 / 9.77 |
| CuRe (確率) | 0.053 / 0.986 | 0.267 / 1.000 | 0.530 / 1.000 |
| UFD (確率) | 0.335 / 0.991 | 0.104 / 0.932 | 0.028 / 0.275 |

- UFD は実写の平均スコアが生成画像を上回る転倒構造
  (実写 0.335 > GPT 0.104 > NB 0.028) のため、しきい値方式では分離不能。
- CF は実写と生成の平均が最も離れており (実写 -9.80 に対し NB -0.70)、
  群単位の実写最大 (-0.54) と生成上位 (6.5〜9.8) の間に明確な余白がある。
  一方で生成下位の半数以上が実写分布に沈むため 90% 検出には届かない。
- CuRe は生成上位 5 群が 0.999 以上に張り付く一方、実写最大も 0.986 と高く、
  しきい値を上げると検出が急減する (誤検知 0 点で 13/91 群)。

## 最終評価 (evaluation 46 群)

較正 `unmet` のため、タスク手順どおり evaluation 分割に適用して判定記録を作成し、
`detecter.evaluation` と `detecter evaluate-pipeline` を CF・CuRe 計測で実行した。
結果は両検出器とも UFD (#50) と同じ構図である。

- 判定記録 (`/tmp/detecter-issue52-cf-eval-decisions.jsonl`,
  `/tmp/detecter-issue52-cure-eval-decisions.jsonl`) は 46 件全件 `inconclusive`。
  - CuRe: `config_invalid` (較正 `unmet` のため)。
  - CF: `config_invalid` に加え `threshold_invalid`。
    CF のしきい値 (-0.1506) は logit のため、`apply_decision` の
    しきい値域チェック (`0 <= threshold <= 1`) を満たさない。
    現行パイプラインは [0, 1] 確率スコアを前提としており、
    logit 検出器のしきい値をそのまま適用できない制約が確認された。
- `detecter.evaluation --unit source_group --split evaluation`
  (`/tmp/detecter-issue52-cf-evaluation.json`,
  `/tmp/detecter-issue52-cure-evaluation.json`):
  実写誤検知率は分母 0 で `not_measured`、全体生成検出率は 0/24 (`measured`)、
  保留率 46/46。UFD (#50) と同一である。
- `detecter evaluate-pipeline`
  (`/tmp/detecter-issue52-cf-pipeline.json`,
  `/tmp/detecter-issue52-cure-pipeline.json`):
  いずれも `status: not_met`。`generator_coverage` は両モデルとも `met`
  (GPT Image 2: 13/10、Nano Banana: 11/10) で、残る未検証理由は
  `decision_config_invalid` のみである。

参考 (未達しきい値を evaluation 群に機械適用した場合の情報値であり、正式な検出率ではない):

| 検出器 | 実写誤検知 (22 群) | 生成検出 (24 群: GPT 13 / NB 11) |
| --- | --- | --- |
| Community Forensics | 2 群 | 6 群 (GPT 0 / NB 6) |
| CuRe | 0 群 | 1 群 (GPT 1 / NB 0) |
| UFD | 0 群 | 0 群 |

CF は evaluation でも Nano Banana のみ 6/11 群がしきい値を上回り、
tuning と同じ生成器傾向が再現した。GPT Image 2 は evaluation 13 群すべてが
しきい値未満である。

## 結論

- UFD 単体 (生成検出 0/91 群) に対し、CF は誤検知 0 の動作点で 28/91 群、
  CuRe は 13/91 群を検出し、同一コホートでの改善方向は確認できた。
  ただし較正目標 (誤検知 0.1% 以下かつ検出 90% 以上) には両検出器とも遠く、
  `unmet` のため最終評価は依然として判定不能である。
- 生成器差が大きく、CF は Nano Banana に偏って強い (tuning 23/46 群、
  evaluation 参考値 6/11 群) 一方、GPT Image 2 は 5/45 群にとどまる。
  生成器ごとの検出器選択・統合が次の検討軸になる。
- CF の logit しきい値は現行 `apply_decision` ([0, 1] 前提) に載らない。
  本格採用にはスコア正規化 (sigmoid 等) か判定側の値域拡張が必要である。
- 実写 105 群の不足 (採用基準 0.1% 以下を証拠立て不可) は本評価でも不変。
  実写増強は別 issue の扱いとする。

## 成果物 (いずれも `/tmp`、リポジトリには含めない)

- `/tmp/detecter-issue52-comparison.jsonl` (660 行、全件 `ok`)
- `/tmp/detecter-issue52-{cf,cure,ufd}-measurements.jsonl` (検出器別 220 行)
- `/tmp/detecter-issue52-{cf,cure,ufd}-tuning-measurements.jsonl` (tuning 174 行)
- `/tmp/detecter-issue52-{cf,cure}-decision-config.json` (いずれも `unmet`)
- `/tmp/detecter-issue52-{cf,cure}-eval-decisions.jsonl` (46 行、全件 `inconclusive`)
- `/tmp/detecter-issue52-{cf,cure}-evaluation.json`
- `/tmp/detecter-issue52-{cf,cure}-pipeline.json` (`not_met`)

## 再現手順

```sh
uv sync --extra community-forensics --extra cure
uv run --extra community-forensics --extra cure \
  python -m detecter.comparison community-forensics ufd cure \
  --ledger /tmp/detecter-issue50-ledger.jsonl \
  --output /tmp/detecter-issue52-comparison.jsonl
# 検出器別・tuning 分割の抽出は image_id 突合せで行う
uv run python -m detecter.calibration \
  --ledger /tmp/detecter-issue50-tuning-ledger.jsonl \
  --measurements /tmp/detecter-issue52-cf-tuning-measurements.jsonl \
  --split tuning --output /tmp/detecter-issue52-cf-decision-config.json
uv run python -m detecter.evaluation \
  --ledger /tmp/detecter-issue50-ledger.jsonl \
  --measurements /tmp/detecter-issue52-cf-measurements.jsonl \
  --decisions /tmp/detecter-issue52-cf-eval-decisions.jsonl \
  --unit source_group --split evaluation \
  --output /tmp/detecter-issue52-cf-evaluation.json
uv run detecter evaluate-pipeline \
  --ledger /tmp/detecter-issue50-ledger.jsonl \
  --decision-config /tmp/detecter-issue52-cf-decision-config.json \
  --measurements /tmp/detecter-issue52-cf-measurements.jsonl \
  --required-generator "GPT Image 2:10" \
  --required-generator "Nano Banana:10" \
  --output /tmp/detecter-issue52-cf-pipeline.json
# CuRe も cf → cure に置換して同様
```

evaluation 用の判定記録は `detecter.cli.apply_decision` で計測へ判定設定を
適用して作成した (`evaluate-pipeline` が判定記録なしで実行する自動生成と同等)。
