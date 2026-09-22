# 全経路の採用可否を報告する

保存済みの台帳、判定設定、計測・判定記録から、最終評価の採用可否を再現可能なJSONで出力します。
既存結果を渡す場合はモデルを起動せず、最終評価を調整用データへ混ぜません。

```sh
uv run detecter evaluate-pipeline \
  --ledger data/ledger.jsonl \
  --decision-config decision-config.json \
  --measurements results/measurements.jsonl \
  --decisions results/decisions.jsonl \
  --comparison results/model-comparison.jsonl \
  --derived-conditions data/derived.conditions.jsonl \
  --output results/final-report.json
```

計測・判定・比較・加工条件・SynthID手動結果は任意の保存済みJSON Linesです。
省略した段階は `insufficient` とし、未検証範囲へ理由を残します。
判定記録を省略して計測記録を渡した場合は、指定した判定設定を各計測へ適用して作成します。
設定の調整用画像と最終評価画像のIDまたは元画像グループが重なる場合は、漏洩として証拠不足にします。

報告の `status` は次のいずれかです。

- `achieved`: 実写の片側95%上限が0.1%以下で、全体生成の検出率が90%以上です。
- `not_met`: 必要な最終評価データはありますが、性能目標を満たしません。未達設定は判定へ適用しません。
- `insufficient_evidence`: 欠測、条件不一致、実写の未判定、空集合、比較不足などで採用可否を決められません。

実写の誤検知率は対象件数、分子、分母、95%上限を保存します。誤検知0件・3000件の固定例は
上限約0.0998%として `fixed_reference` に出力します。生成画像の保留・失敗・未検査は未検出として分母へ残します。
元画像グループ単位の判定反転、加工条件、生成器、撮影機器、部分編集の不足も報告します。

合成画像だけでは実運用性能の証拠にならないため、非機密の評価台帳がない場合は動作確認を行い、
性能報告を `insufficient_evidence` とします。SynthID手動結果がなくても他の段階は実行できます。

モデルや加工をこの処理から実行する場合は、`--run-ufd`、`--run-comparison`、
`--derive-directory` を指定します。外部モデルの取得・CPU計測・画像加工の失敗は報告へ残ります。
採用判定は常に元画像グループ単位で行い、実写の未判定、調整データとのハッシュ重複、
加工条件または比較モデルの不足がある場合は達成にしません。
