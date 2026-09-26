# Issue #67: `detecter analyze` の Jev 最終合成を較正済み統計モデルに置き換え (2026-09-26)

`analyze` の最終合成を TypeSafe Jev から、tuning 群で較正したロジスティック
統合 (`detecter.fusion`) に置き換えた。Jev は数値統合を苦手と明記されており
(#67 背景・`results/jev-camera-comparison.jsonl` の実写→AI寄り判定)、
実測でも実写をAI側に寄せる合成になっていたため、Jevの得意な文章読解でなく
苦手な数値統合を任せていた構造を解消する。

## 1. 実装

### `detecter.fusion` (新規) + `src/detecter/data/fusion_model.json`

- 特徴量は各受動スコア (CF logit / CuRe / UFD) の tuning コホート群内での
  経験的順位 (`rank ∈ [0,1]`、欠測は中立 0.5)。スケールの異なる3スコアを
  無単位化し、tuning 範囲外の値は 0.0/1.0 に飽和するため外挿しない。
- 群単位 (実写=群内 max、生成=群内 min) の tuning スコアでロジスティック回帰を
  L2 正則化つき Newton 法でフィット (純 Python、sklearn 不使用)。
- 確率較正は順位特徴そのものが担う (単調変換 = 等張較正と同等の役割)。
  出力確率は確率的解釈ではなく動作点スコアとして扱う。
- 判定は共有の4状態 `ai_evidence_confirmed` / `ai_likely` / `inconclusive` /
  `no_ai_signal_detected` を返し、`reasons` に根拠を列挙する。
  確定証拠 (信頼済みC2PAのAIクレーム、自動検証済みSynthID) は既存
  `deterministic_bypass` と同じ条件で `ai_evidence_confirmed` に確定する。
- `image_kind` ごとのしきい値: `photo` は EXIF 確認済み実写群 (83群) のみで
  選んだ動作点 (0.537)、`default` (その他全種別) は全実写群 (465群) の
  FP0 動作点 (0.7105)。いずれも tuning で FPR=0.1% (許容FP 0件) の
  動作点。下限の `no_ai_signal_below` (0.0714) は FP0 を保ったまま
  「明確に低い」帯を `no_ai_signal_detected` として切るための保留帯下端。
- 実行時の画像種別は既存の `device_category` から推定する
  (smartphone/camera → photo、その他 → unknown)。台帳上の
  `image_kind` と同名だが別物であり、非写真実写を photo に誤割するリスクは
  残る (§4 観測)。

### `detecter analyze` の変更

- 既定の最終合成は `fusion_verdict` (Jev 非呼び出し・オフライン動作)。
  `--jev` を付けた場合のみ従来通り Jev 合成が最終判定を駆動し、統計統合の
  結果は `breakdown.fusion` に常時記録される (アブレーション比較用)。
  `--no-jev` は非推奨の no-op として残す。
- `breakdown.jev` は Jev を呼ばない既定経路では `null`。

## 2. 統合あり vs 単体ベスト (群単位 TPR@FPR、Issue #64 指標)

同一コホート (sns-q75、tuning 実写465/生成91群、evaluation 実写121/生成24群)、
群集約規則は評価と同一 (実写 max / 生成 min)。表の「FP」は実績FP/許容FP。

| 方式 | tuning FPR=1% | tuning FPR=0.1% | evaluation FPR=1% | evaluation FPR=0.1% |
| --- | --- | --- | --- | --- |
| CF 単体 | 4/4, 3/91 (3.3%) | 0/0, 1/91 (1.1%) | 1/1, 3/24 (12.5%) | 0/0, 3/24 (12.5%) |
| CuRe 単体 | 4/4, 5/91 (5.5%) | 0/0, 0/91 | 1/1, 2/24 (8.3%) | 0/0, 1/24 (4.2%) |
| UFD 単体 | 4/4, 0/91 | 0/0, 0/91 | 1/1, 0/24 | 0/0, 0/24 |
| EFFORT 単体 | 4/4, 9/91 (9.9%) | 0/0, 2/91 (2.2%) | 1/1, 3/24 (12.5%) | 0/0, 2/24 (8.3%) |
| **統合 (CF+CuRe+UFD 順位)** | **4/4, 14/91 (15.4%)** | **0/0, 4/91 (4.4%)** | **1/1, 8/24 (33.3%)** | **0/0, 5/24 (20.8%)** |
| 統合 (CF+CuRe のみ) | 4/4, 3/91 | 0/0, 0/91 | 1/1, 3/24 | 0/0, 0/24 |
| 統合 (CF+CuRe+EFFORT) | 4/4, 10/91 | 0/0, 1/91 | 1/1, 3/24 | 0/0, 3/24 |

- 統合は全動作点で単体ベスト以上 (tuning 0.1%: 4 群 vs CF 1 群 / EFFORT 2 群、
  evaluation 0.1%: 5 群 vs CF 3 群)。Issue #56 の「重み掃引の最良値が
  evaluation に汎化しない」結果と違い、順位特徴 + L2 正則化の素朴なモデルは
  tuning→evaluation で改善が再現したため、統合を有効化する条件を満たした。
- UFD は単体では全く検出しないが統合では有効に働く (CF+CuRe のみ 0/91 →
  +UFD で 4/91)。実写裾が UFD 単体では転倒しているが (#52)、順位空間では
  生成側の高順位シグナルとして寄与する。

## 3. 種別 (image_kind) 別

統合モデル、群単位 (tuning / evaluation):

| 範囲 | tuning FPR=0.1% | evaluation FPR=0.1% |
| --- | --- | --- |
| overall | 0/0, 4/91 | 0/0, 5/24 |
| photo 実写 | 0/0, 28/91 (30.8%) | 0/0, 8/24 (33.3%) |
| unknown 実写 | 0/0, 生成群なし | 0/0, 生成群なし |

- `photo` 動作点 (0.537) では tuning の生成検出が 4/91 → 28/91、
  evaluation も 5/24 → 8/24 に上がる。Issue #64 の観測 (実写高スコア裾が
  `unknown` 種に集中) と整合し、EXIF 確認済み実写に限れば統合の検出率は
  約3〜7倍になる。
- 生成群は全件 `photo` 種のため `photo` 列の生成TPRは全生成群が分母。

## 4. 観測

- **統合は有効化条件を満たした。** 「統合あり vs 単体ベスト」で tuning /
  evaluation の両方・両 FPR で単体ベストを上回る。
- **percent 表示を廃止したわけではない**: `ai_probability` (0.0〜1.0) と
  4状態 + reasons を返す。状態は確率ではなく動作点で決まる。
- **Jev 合成は残っている** (`--jev`)。既定は統計統合であり、Jev 経路の
  復帰はアブレーションで改善が確認できた場合のみ。
- **`photo` 種別の実行時推定は粗い**: EXIF のメーカー情報から
  smartphone/camera を photo とみなすため、EXIF のある非写真
  (スキャン・作成物) を誤って緩いしきい値に通すリスクがある。
  厳密な写真/非写真分類器が入るまでの簡易近似。
- 絶対値は依然低い (evaluation 0.1% で 20.8%)。生成器検出率の向上は
  別 issue の課題であり、ここでは「Jev 合成を統計モデルに置き換える」
  構成変更とその正当化を記録した。

## 再現手順

```sh
# 群集約 (実写=max / 生成=min) した tuning スコアで
# 順位特徴ロジスティック回帰をフィット → src/detecter/data/fusion_model.json
# 係数: bias -4.836037, cf 2.129943, cure 4.353035, ufd -1.329049
uv run python -m unittest discover -s tests  # 194 tests
```
