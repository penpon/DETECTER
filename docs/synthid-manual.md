# SynthIDの手動結果

SynthID（Googleの画像透かし検証サービス）の公式画面で利用者が確認した結果を、
検査した画像のIDとSHA-256に結び付けて保存します。
このコマンドは画像の送信、ブラウザー操作、SynthIDの自動検証を行いません。

台帳の画像IDとSHA-256を指定してください。登録前に実際の画像ファイルとハッシュを
照合するため、別画像のハッシュは拒否します。
次のハッシュ値は説明用です。`evidence.txt` は画面に表示された根拠を記したUTF-8のテキストです。

```sh
uv run python -m detecter.synthid_manual add \
  --image image.jpg --image-id image-001 \
  --sha256 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef \
  --state detected --checked-at 2026-09-22T12:00:00Z \
  --route '公式検証画面' --evidence evidence.txt --registrant operator-1 \
  --output results/synthid-manual.jsonl
```

共通CLIの接続後は、`python -m detecter.synthid_manual` の部分を
`detecter synthid-manual` に置き換えられます。

`state` は4種類です。

- `detected`: 公式画面で透かしを検出したという手動記録です。
- `not_detected`: 公式画面で透かしが検出されなかったという手動記録です。実写の証明ではありません。
- `not_checked`: 公式画面で未検査です。確認日時、確認経路、画面の根拠は指定しません。
- `unverifiable`: 確認を試みましたが、結果を確認できませんでした。根拠に理由を記します。

未検査以外は、タイムゾーンを含む `--checked-at`、`--route`、`--evidence` が必須です。
`--registrant` には手動登録者または登録元を指定します。
確認日時はUTCで保存し、別に登録日時 `registered_at` も保存します。

すべての記録で `manual: true`、`automatically_verified: false` を保持します。
`signature_state: not_checked` は、この記録では署名を検査していないことを表します。
`binding_state: match` はローカル画像と指定されたSHA-256が一致したことだけを表します。
公式画面の操作や表示内容を暗号学的に証明したという意味ではありません。

`generation_scope` は初期値が `unknown` です。
検出時に画面の根拠から範囲を記録する場合だけ、`--generation-scope partial`（部分編集）
または `--generation-scope full`（全体生成）を指定できます。
この範囲も手動入力であり、全体生成を確定する判定へ変換しません。
正解ラベルや画像モデルの入力も生成しません。

保存先にはJSON Lines形式で追記し、同じ記録を標準出力に表示します。
`--output -` は標準出力のみです。検証や保存に失敗した場合の終了コードは2です。
未検査を明示したい場合も同じ台帳キーを指定できます。

```sh
uv run python -m detecter.synthid_manual add \
  --image image.jpg --image-id image-001 \
  --sha256 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef \
  --state not_checked --registrant operator-1
```

手動記録は計測結果とは別ファイルに保存します。この記録がなくても既存の解析や評価は動作します。
結果を参照するときは画像IDとSHA-256の両方を照合してください。

```sh
uv run python -m unittest discover -s tests -p test_synthid_manual.py
```

テストは一時的な合成画像を使い、外部サービスへ接続しません。
