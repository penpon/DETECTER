# 評価・判定処理の共有契約

出発点は `215e109` です。既存 `analyze` の schema_version=1、
`media`、`c2pa`、`universal_fake_detect`、`verdict` とJevのA/B比較を維持します。
以下は独立した評価処理のJSON契約です。各issueは専用モジュール、テスト、
`docs/` の説明を所有します。#2〜#10は `python -m detecter.<専用モジュール>`
で独立実行できます。共通CLIの `detecter <コマンド>` への接続は #11 がまとめて担当します。

## 評価台帳（1画像につきJSON Linesの1行）

- `image_id`: 台帳内で一意の文字列。派生画像は新しいIDを持ちます。
- `path`: 画像パス。相対パスは台帳ファイルの親ディレクトリ基準です。
- `source_group`: 独立した元画像を識別する文字列。派生画像で変えません。
- `sha256`: 画像ファイル全体のSHA-256、小文字の16進数64文字です。
- `source`、`license`: 出所と利用条件を示す空でない文字列です。
- `label`: `real`（実写）、`generated`（全体生成）、`edited`（部分生成編集）、
  `unknown`（不明）のいずれかです。通常現像、HDR、ノイズ除去で変更しません。
- `split`: `unassigned`、`tuning`（調整用）、`evaluation`（最終評価用）です。
- `history`: 加工条件オブジェクトの配列です。未加工は空配列です。
- `generator`、`camera`: 任意の文字列です。生成器と撮影機器を評価側で識別します。
- 派生画像の `source_image_id`、`source_sha256`: 元画像のIDとハッシュです。
  `source_group`、ラベル、分割先を継承し、加工履歴を追記します。

正解ラベルは評価側だけが使います。推論関数へ台帳行全体を渡さず、
画像パスと計測に必要な識別子だけを渡します。分割は元画像グループ単位で固定します。

## 計測記録

`schema_version: 1`、`image_id`、`sha256`、`model`、`model_version`、
`weights_version`、`preprocessing_version`、`preprocessing`（条件オブジェクト）、
`environment`（Python、ライブラリ、実行機器）、`status`（`ok` / `error`）、
`raw_score`（成功時の有限数値、失敗時null）、`error`（失敗理由、成功時null）を保存します。
派生条件を追えるよう `source_sha256` と `history` も保存できます。
再利用キーは画像ID・ハッシュとモデル・重み・前処理の全識別情報です。
失敗した画像も1行残します。スコアは正しさの確率ではありません。

## 判定設定と判定記録

判定設定は `config_id`、`calibration_id`、`calibration_images`
（`image_id`、`sha256`、`source_group` の配列）、モデル・重み・前処理の上記4識別子、
`threshold`、`comparison: ">="`、`targets`、`status`
（`candidate` / `unmet` / `validated`）、`usage`（`evaluation` / `production`）を持ちます。
同点スコアは同じ判定です。境界選択には `tuning` だけを使います。
候補を本番設定へ自動昇格させません。必須来歴検査は `required_provenance` の配列で指定します。

判定記録は `image_id`、`sha256`、モデル・重み・前処理の識別情報、`config_id`、
`state`（`ai_likely` / `no_ai_signal_detected` / `inconclusive`）、
`reasons`（判定理由と診断上の矛盾）を保持します。`hold_reasons` は
`inconclusive` の理由だけを含みます。欠測と0%を区別します。
評価は画像単位と元画像グループ単位を明示し、失敗・保留した生成画像も分母に残します。

## 来歴

署名の暗号学的有効性、署名者の信頼、画像との対応、全体生成と部分編集を別々に保存します。
信頼アンカーは利用者が指定したローカルファイルだけを使います。
SynthIDの手動結果は `image_id` と `sha256` に結び、計測や正解ラベルから分離します。
未検査でも他の処理は実行できます。

## 作業の依存関係

#1完了後に #2〜#7 を開始できます。#8は #4、#9は #6、#10は #3と #5、
#11は #2と #3と #9、#12は #8と #10と #11 の完了を待ちます。
CLIの公開処理とJSON入出力が各issueのテスト対象です。モデル・ネットワークの境界だけを
スタブへ置き換え、既存のunittestを使います。通常テストにGPU、写真、APIキーを要求しません。
