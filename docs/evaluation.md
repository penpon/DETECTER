# 保存済み結果の評価

画像をモデルへ再送せず、台帳・計測・判定を画像IDとハッシュで照合します。
同じ呼出しへ異なるモデル条件や判定設定を混ぜると失敗します。

```sh
uv run python -m detecter.evaluation --ledger data/ledger.jsonl \
  --measurements results/measurements.jsonl --decisions results/decisions.jsonl \
  --unit source_group --split evaluation --output -
```

Issue #11で統合するCLIは `uv run detecter evaluate` に同じ引数を渡します。
画像単位は `--unit image` です。各指標は対象件数、分子、分母、除外件数と理由を持ちます。
空集合は `insufficient_data`、未計測しかない対象は `not_measured` として率をnullにします。
生成画像は失敗・保留・欠測も分母に残します。実写誤検知率は判定できた実写を分母にし、
未判定実写の除外理由を表示します。実行失敗率と保留率の分母は全対象です。
不明ラベルはクラス別の性能指標から除き、件数を別途表示します。

元画像グループ単位では、実写はどれか1枚の誤検知で誤検知とし、
生成・部分編集はグループ内の全条件を検出したときだけ検出とします。
元画像と派生画像で分母を水増ししません。加工履歴・生成器・撮影機器別にも同じ規則を適用します。
判定反転は同じ元画像グループに有効な陽性と陰性の両方がある場合です。
`targets` にID・ハッシュ・元画像グループ・分割先・保留理由を残して再集計できます。
