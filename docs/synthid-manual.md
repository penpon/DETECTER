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

## 解析レポートへの結び付け

画像解析では、手動結果を他の根拠と区別して確認できます。
画像IDとSHA-256の両方が一致した記録だけを結び付け、ハッシュ不一致の結果は結び付けません。
`synthid` に確認状態（`detected` / `not_detected` / `not_checked` / `unverifiable`）と
確認日時・確認経路・根拠をそのまま表示し、手動記録であることを明示します。
この結び付けはC2PAの署名・信頼・画像との結び付きの状態を変更せず、暫定判定も変えません。
検出はGoogleのAIによる生成または編集の証拠として扱い、画像全体の生成確定へ拡張しません。
未検出から実写や他社AIの否定は導きません。

```sh
uv run detecter analyze image.jpg --skip-ufd \
  --synthid-manual results/synthid-manual.jsonl --output -
```

手動記録の画像IDは、登録時の `--image-id` と解析時の画像ID（既定は解決済みパス）が
一致する必要があります。記録がない画像や未確認の画像も既存の解析を続行でき、
その場合は `synthid.status: not_linked` として理由を残します。

```sh
uv run python -m unittest discover -s tests -p test_synthid_manual.py
```

テストは一時的な合成画像を使い、外部サービスへ接続しません。
