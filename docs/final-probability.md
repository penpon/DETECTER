# 最終AI確率（Jevによる文脈統合）

`detecter.final_probability` は、基底AI確率（#40の
`calibrated_ai_probability`）とサニタイズ済みメタデータをTypeSafe Jev
（System One、`jev-1.13.0`）へ渡し、最終AI確率
`final_ai_probability ∈ [0.0, 1.0]` と信頼度スコアを返します。
画像バイト列や自由文は送りません。

```python
from detecter.final_probability import final_ai_probability
result = final_ai_probability(
    client, cf_score=-7.0, cure_score=0.05, ufd_score=0.93,
    device_category="smartphone",
    computational_photography_detected=True,
)
result["final_ai_probability"]  # 0.0〜1.0
```

## サニタイズ済みState

`build_final_state` がJevへ渡すStateを作ります。構成するのは数値・
真偽値・固定列挙のみで、パス・ハッシュ・Make/Model・UserComment等の
自由文は一切含めません。含まれるのは次のキーです。

- `base_ai_probability` / `base_partial`: 基底確率と欠測フラグ。
- `passive_scores`: 3モデルの正規化スコア（CF384はシグモイド変換）。
- `passive_outlier_models` / `lone_outlier`: 他モデルと0.5境界で
  正反対に分かれるモデルの一覧。
- `c2pa`: `status`・`confirmation_state`・`ai_claim`・`generation_scope`
  の列挙値のみ。
- `synthid_state`、`device_category`、
  `computational_photography_detected`、`image`（幅・高さ・形式）。

## Jev質問仕様

`jev_questions` は1回の `system_one` 呼び出しで3問を並列評価します。

- `ai_involvement`（Choice）: `ai_generated`・`ai_edited`・
  `authentic_capture`・`inconclusive` の確率分布。
- `evidence_conflict`（Noul）: シグナル間の矛盾度（0.0〜1.0）。
- `confidence`（Score）: 証拠の信頼度を0〜4段階で評価。

指示文には「受動スコアは較正済み確率ではない」「
`computational_photography_detected` が真で単一モデルのみ外れ値なら
端末の処理パイプラインを優先説明とする」旨を明記し、
iPhone実写でUFDのみスパイクする場合の過剰な跳ね上がりを抑制します。

## 合成と信頼度

`final = w * P_jev + (1 - w) * max(base, passive_scores)` です。
`P_jev` は `ai_generated`＋`ai_edited` の確率質量、
`w = 0.5 * (1 + confidence)` でJevの信頼度が高いほどJev側へ寄せます。
`confidence` はScore回答の確信度に `1 - 0.5 * evidence_conflict`
を掛けた連続値です。

Jevのリクエストが失敗した場合は例外を投げず
`status: "error"` とStateを返して診断できるようにします。

```sh
uv run python -m unittest discover -s tests -p test_final_probability.py -v
```
