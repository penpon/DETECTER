# 統一AI確率CLI（`detecter analyze`）

画像パスを1つ以上渡すだけで、確定バイパス → 3モデル受動推論 → 統計
キャリブレーション → 較正済み統計統合の全パイプラインを完全自動で実行し、
`ai_probability`（0.0〜1.0）を含む統一JSONを1画像1行で標準出力します。
外部GPUサーバーや非同期キューは不要で、CPUだけで1画像数秒程度で終了します。

```sh
uv run detecter analyze path/to/image.jpg
uv run detecter analyze path/to/images --output results/analyze.jsonl
```

ディレクトリは再帰的に探索します。既定ではファイルを保存せず標準出力のみです。
`--output` を指定するとJSON Linesへ追記します。CPUが既定で、`--device auto`
でもCUDAは使いません。最終合成は既定で統計統合（`detecter.fusion`）です。
比較用にJev合成を復帰する場合のみ `--jev` を付けてください（`--no-jev` は
非推奨の no-op）。

## 出力JSONスキーマ（`schema_version: 1`）

- `ai_probability`: 最終AI確率（0.0〜1.0）。画像が読み込めなかった
  場合のみ `null`。
- `ai_probability_percent`: `"8.4%"` 形式の表示用文字列。
- `confidence`: 判定の信頼度（0.0〜1.0）。確定バイパスは1.0、
  Jev応答時はJevの確信度、Jev不在時は基底確率の固定値。
- `state`: `ai_confirmed` / `real_confirmed`（確定バイパス）、
  `ai_evidence_confirmed` / `ai_likely` / `inconclusive` /
  `no_ai_signal_detected`（統計統合の4状態）、
  `ai_generated` / `ai_edited` / `authentic_capture` / `inconclusive`
  （`--jev` 時のJev関与判定）、`error`（画像読み込み失敗）。
- `breakdown.c2pa`: C2PA検証結果（署名・信頼・結合・生成範囲）。
- `breakdown.synthid`: SynthID状態。自動検証経路は未接続のため、
  `--synthid-manual` で登録済みJSON Linesを渡すと `linked` に反映します。
- `breakdown.raw_scores`: CF384・CuRe・UFDの生スコア（欠測は `null`）。
- `breakdown.models`: 3モデルの計測記録（モデル版・重み・前処理・環境・
  ステータス・エラー）。
- `breakdown.base_probability`: #40のロジスティック統合結果
  （`probability`、`logit`、重み、`missing_scores`、モデル条件）。
- `breakdown.camera`: サニタイズ済みEXIFカメラ情報（Make/Model/露出等）。
- `breakdown.device_category`: `smartphone` / `camera` / `scanner` / `unknown`。
- `breakdown.computational_photography_detected`: Smart HDR / Deep Fusion等の
  処理痕跡フラグ。
- `breakdown.fusion`: #67の統計統合結果（`state`、動作点しきい値、
  `reasons`、順位特徴 `ranks`、欠測フラグ）。
- `breakdown.jev`: `--jev` 指定時のみ #42の最終合成結果。既定では null。

## 各レイヤーの動作

1. **確定バイパス**（#41 `deterministic_bypass`）: 信頼済みC2PAにAI生成・
   編集クレーム、または自動検証つきSynthID検出があれば `ai_probability` を
   1.0、ハードウェア署名（Secure Enclave / StrongBox）かつAIクレームなし
   であれば 0.0 で即確定します。この場合受動モデルは一切起動しません。
2. **受動推論**: `community_forensics.measure`（CF384ロジット）、
   `cure.measure`（softmax確率）、`ufd_batch.measure`（sigmoidスコア）を
   CPUで実行します。モデル不在や重み未取得はそのモデルの記録を `error`
   にし、残りで継続します。
3. **統計キャリブレーション**（#40 `calibrated_ai_probability`）: 生スコアを
   固定係数のロジットへ合成し `base_ai_probability` を得ます。欠測スコアは
   中立寄与で除外し `partial: true` を残します。
4. **統計統合**（#67 `fusion_verdict`）: 順位特徴ロジスティック統合の
   確率を画像種別ごとの動作点で4状態判定へ写像します。`--jev` 指定時は
   従来のJev最終合成（#42 `final_ai_probability`）が代わりに判定を駆動し、
   統計統合結果は比較用に `breakdown.fusion` へ残ります。
   を得ます。`TYPESAFE_API_KEY` がない・リクエスト失敗時は例外にせず、
   基底確率へフォールバックして `state` に理由を残します。

## 終了コード

- `0`: 全画像のレコードを出力しました。
- `1`: 一部または全部の画像で `state: error` のレコードを出力しました。
- `2`: 引数・入力が不正です（画像なし、不正なオプション等）。

## 備考

- `analyze` の旧来の詳細記録（UFD暫定判定・`--decision-config`・
  `--jev-compare` 等）は `detecter analyze-legacy` に残しています。
- SynthID自動検証は外部サービス接続を伴うため未実装です。手動登録結果は
  `--synthid-manual` で取り込み、自動検証フラグのある登録だけが
  バイパスへ効きます。
- 0%・100%は確定証拠がある時だけ出ます。受動スコアのみの結果は
  「AIを示す信号なし」の確率であって実写の証明ではありません。

```sh
uv run python -m unittest discover -s tests -p test_ai_probability.py -v
```
