# 調整用データで候補を選び、最終評価で一度だけ評価する

UFD、Community Forensics、CuReを同じ調整用の元画像グループで比較し、
調整用データだけで候補としきい値を固定してから、独立した最終評価用データを
一度だけ評価します。未使用の最終評価結果を見て候補やしきい値を選び直しません。

```sh
uv run detecter select-candidate select \
  --tuning-ledger ledger/tuning-ledger.jsonl \
  --candidate ufd=results/tuning-ufd.jsonl \
  --candidate community-forensics-384=results/tuning-community-forensics.jsonl \
  --candidate cure=results/tuning-cure.jsonl \
  --output results/selection.json
uv run detecter select-candidate finalize \
  --ledger ledger/cohort-final-ledger.jsonl \
  --selection results/selection.json \
  --measurements results/final-measurements.jsonl \
  --comparison results/model-comparison.jsonl \
  --derived-conditions data/derived.conditions.jsonl \
  --required-generator 'GPT Image 2.5:29' \
  --required-generator 'Nano Banana Pro:29' \
  --output results/final-selection-report.json
```

調整用の計測は `detecter compare` で同じ台帳から作ります。
各記録のモデル・重み・前処理の識別情報は計測時に保存され、
選択処理は候補ごとに照合します。異なるモデルのスコアを平均したり
多数決したりしません。

## 候補の選択（`select`）

- 全候補に同じ調整用台帳を渡します。台帳と計測の画像ID集合の完全一致、
  ハッシュ照合、モデル条件の一致は候補ごとに検査します。
- 各候補のしきい値は `detecter.calibration` と同じ規則で調整用データから選び、
  実写誤検知率目標を満たす候補だけを採用対象にします。
- 選択規則は最終評価の前に固定され、選択記録へ保存されます。
  生成画像検出数、保留数、失敗数、しきい値、設定識別子の順で決定的に選び、
  入力の行順に依存しません。
- 選択記録は `selection_id`（内容のSHA-256）で改変を検知できます。
  候補の条件、前処理、しきい値、調整用指標（分子・分母・率・状態）、
  元画像グループ集合を含みます。

終了コードは候補の固定が0、採用候補なしが1、入力や保存の失敗が2です。
条件を満たす候補がない場合は `status: no_candidate` と報告し、
未達の設定を検証済み・本番用として保存しません。

## 最終評価（`finalize`）

- 固定した設定（モデル、重み、前処理、しきい値）で最終評価用データを一度評価します。
  判定記録の省略時は、固定設定を各計測へ適用して作成します。
- 選択記録の完全性と固定設定の識別子を検証してから評価します。
  改変や条件不一致がある場合は証拠不足として採用しません。
- 最終評価は `detecter evaluate-pipeline` と同じ基準で報告します。
  実写誤検知率の片側95%上限、生成画像検出率の片側95%下限、
  必須生成器群の最小独立元画像数、生成器別・撮影機器別・部分編集別の
  分子・分母・保留・失敗・評価範囲を含みます。
- 最終評価結果を見て候補やしきい値を選び直した場合は
  `--reselected-after-final` を指定します。この最終評価は採用根拠にせず、
  新しい未使用データが必要だと報告します。

終了コードは達成・証拠不足が0、未達または採用候補なしが1、
入力の失敗が2です（`evaluate-pipeline` と同じ対応）。

採用候補の設定は再現可能な評価結果として保存しますが、
既定の本番設定を自動で置き換えません。`finalize` は報告書だけを書き、
判定設定ファイルを検証済み・本番用へ書き換えません。

```sh
uv run python -m unittest discover -s tests -p 'test_selection.py' -v
```

テストは固定した小さな計測記録を使います。写真、GPU、外部サービスは不要です。
