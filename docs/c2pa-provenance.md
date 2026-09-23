# C2PAの来歴検査

C2PA（画像に埋め込まれた来歴情報の規格）の検査では、署名の有効性、署名者の信頼、
検査した画像との一致を別々に記録します。画像モデルや正解ラベルは使いません。

既存の解析コマンドでも、`c2pa` に確認状態と保留理由が追加されます。

```sh
uv run detecter analyze image.jpg --skip-ufd --c2pa-trust-anchors anchors.pem --output -
```

独立した検査では、評価台帳の画像IDとファイル全体のSHA-256ハッシュを記録できます。
`--sha256` を指定すると台帳のハッシュと照合します。次のハッシュは説明用の値です。

```sh
uv run python -m detecter.c2pa_provenance image.jpg \
  --image-id image-001 \
  --sha256 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef \
  --c2pa-trust-anchors anchors.pem --output results/provenance.jsonl
```

`--output` の指定先へJSON Lines形式で追記し、同じ記録を標準出力にも出します。
省略時または `--output -` では標準出力だけに出します。
`--skip-c2pa` を指定すると、画像のIDとハッシュを保存したまま未検査として記録します。
検査エラーは記録して終了コード1、引数や画像ファイルの不備は終了コード2です。
署名未信頼やハッシュ不一致は有効な検査結果なので終了コード0です。

`confirmation_state` は次の確認状態です。

- `not_checked`: 来歴を検査していません。
- `absent`: 埋め込まれた来歴情報がありません。
- `unverifiable`: 検証エラー、署名の不備、検証結果の不足または形式不備があります。
- `untrusted`: 署名は有効ですが、署名者を信頼できません。
- `hash_mismatch`: マニフェストと画像、または台帳と画像のハッシュが一致しません。
- `binding_unknown`: 署名は有効ですが、検査画像との一致を確認できません。
- `cryptographically_valid`: 署名と画像の一致は有効ですが、署名者の信頼を確認していません。
- `trusted`: 署名、明示された信頼アンカー、画像との一致を確認しました。

個別の結果は `signature_state`（`valid` / `invalid` / `unknown` / `not_checked`）、
`trust_state`（`trusted` / `untrusted` / `unknown` / `not_checked`）、
`binding_state`（`match` / `mismatch` / `unknown` / `not_checked`）に保存します。
`confirmed` がtrueになるのは `trusted` のときだけです。
`trusted` という真偽値は署名者の信頼だけを表すため、画像との一致には `confirmed` を使います。

`reasons` は保留理由です。`asset_hash_mismatch` は画像との不一致、
`asset_binding_unknown` は画像との対応不明、`input_sha256_mismatch` は台帳との不一致を示します。
`signature_*` と `signer_*` は署名・署名者の不足した確認状態です。
`validation_failed` は検証失敗、`invalid_validation_results` は検証結果の形式不備を示します。
`c2pa_not_checked`、`c2pa_absent`、`c2pa_unverifiable` は検査全体の状態を示します。

`generation_scope` は `full`（全体生成）、`partial`（部分生成編集）、`unknown`（不明）です。
対象マニフェストの `c2pa.actions` / `c2pa.actions.v2` から判定します。
生成を示す作成操作だけを全体生成とし、合成や生成を伴う編集操作は部分編集として扱います。
部分編集の記録が併存する場合は部分編集を優先します。
素材となった別画像の履歴は、検査画像の全体生成の根拠にしません。
既存の暫定判定でも部分編集の範囲を明記します。

C2PA 2.4の `c2pa.ai-disclosure` も対象マニフェストからのみ読み、
`ai_disclosure`（`model_type`、`model_name`、`model_identifier`、
`human_oversight_level`、`scientific_domain`）と
`ai_disclosure_assertion`（開示の有無）として既存のアクション情報と
ともに保存します。署名の有効性、署名者の信頼、画像との一致、
全体生成／部分編集は別々の項目に残し、開示の有無で上書きしません。
未信頼、未検証、画像との結び付きが不明な主張は確認済みのAI生成根拠にしません。
信頼済みで画像に結び付いたAI生成根拠と低い分類器スコアが併存する場合は、
最終状態を「AIの信号なし」にせず、根拠の食い違いを理由に明示します。

検証コードは `activeManifest` の `success`、`failure`、`informational` を区別して読みます。
説明文の文字列や素材画像の検証成功は、検査画像との一致の根拠にしません。
元の `validation_results` も保存します。
信頼アンカーは `--c2pa-trust-anchors` で指定されたローカルファイルだけを読みます。
遠隔マニフェストと証明書失効情報の自動取得は無効です。
Jev（既存の判定比較に使うモデル）へ渡す入力のフィールド構成は維持します。

```sh
uv run python -m unittest discover -s tests -p test_c2pa_provenance.py
```

テストは合成画像と検証結果の代替データを使います。外部写真や秘密鍵は必要ありません。
