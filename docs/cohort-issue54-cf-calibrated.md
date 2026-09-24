# Issue #54: Community Forensics の logit しきい値を判定パイプラインへ適用可能にする (2026-09-24)

Issue #52 で Community Forensics (CF) は誤検知 0 の動作点で生成 28/91 群を検出したが、
較正しきい値 -0.1506 (logit) が `apply_decision` の `0 <= threshold <= 1` チェックに抵触し、
evaluation 46 件全件が `inconclusive` (`config_invalid` + `threshold_invalid`) になった。
本 issue では `detecter` 側を最小差分で修正し、正規化後のスコアで
tuning 較正 → evaluation 判定 → evaluate-pipeline を再実行した記録である。

## コード変更 (最小差分)

検討した方針と選択理由:

1. CF 計測で `raw_score` に sigmoid 併記・別フィールド化:
   `calibration` と `apply_decision` の両方に読替が必要で差分が大きい。
   さらに `docs/community-forensics.md` は `raw_score` を「シグモイド関数適用前」と明記しており、
   計測意味の変更は検証スクリプト (`scripts/verify_community_forensics.py`) や
   既存記録との整合性も崩す。
2. calibration 入力時に CF 行だけ sigmoid 変換:
   コード変更なしで済むが、将来の CF 計測が依然パイプラインに載らない一時しのぎになる。
3. `apply_decision` の値域チェック緩和:
   1 箇所の削除。`docs/contracts.md` は「スコアは正しさの確率ではありません」と明記し、
   `docs/calibration.md` と `validate_config` はしきい値に有限性しか要求していない。
   `[0, 1]` チェックは契約と不整合な追加制約だった。

3 を採用した。`src/detecter/cli.py` の `apply_decision` から `threshold_invalid` 分岐を削除し、
有限性検証は `validate_config` に一本化した。
計測記録フォーマット・既存ファイルは無変更で互換性を保つ。
`threshold_invalid` という理由文字列自体が消滅する (他に参照はない)。

テストは `tests/test_decision_cli.py` の既存パターンに従い 2 件追加した。
ヘルパーにモデル条件の上書き引数を足し (既定は従来どおり UFD)、
logit しきい値 -0.1506 での適用 (境界の同点を含む `ai_likely`/`no_ai_signal_detected` 判定と
`threshold_invalid` の不在) と、非数値しきい値の保留継続 (`config_invalid` のみ) をカバーする。

なお `analyze-legacy` の `--threshold` 直接指定に対する `[0, 1]` ガードは対象外とした。
UFD 既定経路の UX ガードであり、較正 → 評価パイプラインは `apply_decision` 経由のためである。

## 実験

`/tmp/detecter-issue52-comparison.jsonl` の CF 220 行に安定 sigmoid
(`x >= 0` では `1/(1+exp(-x))`、そうでなければ `exp(x)/(1+exp(x))`) を適用し、
他フィールド同一の計測ファイルを派生させた。順序保存は全行の順位一致で確認済み。
tuning 174 行は `/tmp/detecter-issue50-tuning-ledger.jsonl` との image_id 突合せで抽出した
(#52 と同じ方法)。

```sh
uv run python -m detecter.calibration \
  --ledger /tmp/detecter-issue50-tuning-ledger.jsonl \
  --measurements /tmp/detecter-issue54-cf-sigmoid-tuning-measurements.jsonl \
  --split tuning --output /tmp/detecter-issue54-cf-sigmoid-decision-config.json
uv run python -m detecter.evaluation \
  --ledger /tmp/detecter-issue50-ledger.jsonl \
  --measurements /tmp/detecter-issue54-cf-sigmoid-measurements.jsonl \
  --decisions /tmp/detecter-issue54-cf-sigmoid-eval-decisions.jsonl \
  --unit source_group --split evaluation \
  --output /tmp/detecter-issue54-cf-sigmoid-evaluation.json
uv run detecter evaluate-pipeline \
  --ledger /tmp/detecter-issue50-ledger.jsonl \
  --decision-config /tmp/detecter-issue54-cf-sigmoid-decision-config.json \
  --measurements /tmp/detecter-issue54-cf-sigmoid-measurements.jsonl \
  --required-generator "GPT Image 2:10" \
  --required-generator "Nano Banana:10" \
  --output /tmp/detecter-issue54-cf-sigmoid-pipeline.json
```

evaluation 用の判定記録は #52 と同様に `detecter.cli.apply_decision` で作成した
(`evaluate-pipeline` の自動生成と同等)。

## 結果

- 較正 (tuning 174 群): `status: unmet` (終了コード 1)、しきい値 0.4624 (`[0, 1]` 内)、
  実写誤検知 0/83 群、生成検出 28/91 群 (30.8%)。
  sigmoid は単調変換のため #52 の logit 較正 (-0.1506) と選択・指標が完全一致する。
  目標 (誤検知率 0.1% 以下かつ検出率 90% 以上) 未達のため `candidate` にならず、
  正式な検出率の適用条件を満たさない旨をここに記録する。
- 判定適用 (evaluation 46 群): 手順どおり実施。全件 `inconclusive`、
  理由は `config_invalid` のみ。`threshold_invalid` は消滅し、要件を満たした。
  修正後コードで既存 logit 計測 + 既存設定を適用しても同じく `config_invalid` のみとなり、
  既存記録の互換性を確認した。
- `detecter.evaluation` (`--unit source_group --split evaluation`):
  実写誤検知率は分母 0 で `not_measured`、全体生成検出率は 0/24 (`measured`)、保留率 46/46。
  #52 と同一の構図である。
- `detecter evaluate-pipeline`: `status: not_met`。
  `generator_coverage` は両モデルとも `met` (GPT Image 2: 13/10、Nano Banana: 11/10) で、
  残る未検証理由は `decision_config_invalid` のみである。

参考 (未達しきい値を evaluation 群に機械適用した場合の情報値であり、正式な検出率ではない。
logit/sigmoid 両尺度で一致):

| 尺度 | 実写誤検知 (22 群) | 生成検出 (24 群: GPT 13 / NB 11) |
| --- | --- | --- |
| sigmoid (0.4624) | 2 群 | 6 群 (GPT 0 / NB 6) |
| logit (-0.1506) | 2 群 | 6 群 (GPT 0 / NB 6) |

## 結論

- パイプラインは logit 検出器のしきい値を扱えるようになった (`threshold_invalid` の消滅)。
- CF の正式な検出率は較正 `unmet` のため依然として確定不能
  (0/24 `measured`、保留 46/46、pipeline `not_met`)。
  sigmoid 正規化は順序を変えないため、検出率自体の改善には寄与しない。
- 次の軸は検出率の向上 (生成器ごとの検出器選択・統合) であり、本 issue の範囲外とする。

## 成果物 (いずれも `/tmp`、リポジトリには含めない)

- `/tmp/detecter-issue54-cf-sigmoid-measurements.jsonl` (CF 220 行、sigmoid 適用)
- `/tmp/detecter-issue54-cf-sigmoid-tuning-measurements.jsonl` (tuning 174 行)
- `/tmp/detecter-issue54-cf-sigmoid-decision-config.json` (`unmet`、しきい値 0.4624)
- `/tmp/detecter-issue54-cf-sigmoid-eval-decisions.jsonl` (46 行、全件 `inconclusive`)
- `/tmp/detecter-issue54-cf-sigmoid-evaluation.json`
- `/tmp/detecter-issue54-cf-sigmoid-pipeline.json` (`not_met`)

リポジトリの変更は `src/detecter/cli.py`、`tests/test_decision_cli.py`、
本ドキュメントのみである。

## 再現手順

```sh
uv run python -m unittest discover -s tests
uv run ruff format --check src/detecter/cli.py tests/test_decision_cli.py
uv run ruff check src/detecter/cli.py tests/test_decision_cli.py
```

計測派生と較正・評価の再実行は「実験」節のコマンドどおり。
sigmoid 派生スクリプトは順序保存の表明 (`assert`) を含み、較正の終了コード 1 は
`unmet` の正常終了である。
