# 固定した判定設定を解析へ適用する

調整用データから作成した判定設定を指定すると、画像解析は設定のモデル版・重み版・
前処理版・設定識別子を計測結果と照合してから、`score >= threshold` を適用します。
設定を指定しない場合、既存の暫定 `verdict` は互換性のため残りますが、
新しい `decision` は `inconclusive` として設定欠落を記録します。

```sh
uv run detecter analyze image.jpg \
  --decision-config decision-config.json --output -
```

設定ファイルが壊れている、未達である、設定識別子が内容と一致しない、
本番用途なのに検証済み本番設定でない場合は、未調整のしきい値へ戻さず終了コード2で停止します。
設定を読み込めた場合も、画像ごとのモデル条件、スコア、画像ハッシュ、必須来歴を照合します。
不一致・欠測・実行失敗・ハッシュ不一致は `decision.state: inconclusive` として、
`decision.reasons` と `decision.hold_reasons` に残します。

出力は従来の `universal_fake_detect`、`c2pa`、`verdict` を維持し、設定を使った結果を
別の `decision` オブジェクトへ保存します。`decision.config_id` と `calibration_id` は設定の識別子です。
UFDの低スコアは実写の証明になりません。C2PAの未信頼、確認不能、部分編集は全体生成の
確認済みへ変換しません。部分編集を検出した場合は `generation_scope: partial` を残します。
信頼済みで画像に結び付いたAI生成根拠があるのに分類器スコアが低い場合は、
`decision.state` を `no_ai_signal_detected` にせず `ai_likely` とし、
`reasons` に `c2pa_ai_evidence_with_low_classifier_score` を残します。
この根拠の食い違いは保留状態ではないため `hold_reasons` には含めません。

`--decision-usage evaluation`（既定）は候補設定を評価へ適用できます。
`--decision-usage production` は `status: validated` かつ `usage: production` の設定だけを許可します。
候補設定を本番用途へ自動昇格させる処理はありません。

後続処理の専用入口も共通CLIへ接続しています。

```sh
uv run detecter ledger validate data/ledger.jsonl
uv run detecter evaluate --ledger data/ledger.jsonl \
  --measurements results/measurements.jsonl --decisions results/decisions.jsonl --output -
uv run detecter calibrate --ledger data/ledger.jsonl \
  --measurements results/measurements.jsonl --split tuning --output decision-config.json
```

```sh
uv run python -m unittest discover -s tests -p 'test_decision_cli.py' -v
```
