# 評価画像の台帳

`detecter.ledger` は画像を収集せず、既存画像の台帳の検証と元画像グループ単位の分割を行います。
画像・台帳はローカルに置き、リポジトリへ追加しません。形式は [共有契約](contracts.md) に従います。

## 入力と検証

入力は1画像につき1行のJSON Linesです。次は形式の例です。`sha256` は実ファイルのSHA-256へ置き換えます。

```json
{"image_id":"photo-1","path":"images/photo-1.png","source_group":"original-1","sha256":"0000000000000000000000000000000000000000000000000000000000000000","source":"所有者による撮影","license":"評価利用を許諾","label":"real","split":"unassigned","history":[],"camera":"camera-a"}
```

画像パスは台帳ファイルの親ディレクトリ基準です。`label` は `real`（実写）、`generated`（全体生成）、
`edited`（部分生成編集）、`unknown`（不明）の4種類です。`history` は加工条件オブジェクトの配列です。
通常現像、HDR、ノイズ除去は加工履歴へ記録し、実写ラベルを変更しません。不明ラベルも自動変更しません。

```sh
uv run python -m detecter.ledger validate data/ledger.jsonl
```

必須項目、画像ID・画像ハッシュの重複、実ファイルとのハッシュ一致、同じ `source_group` 内の
ラベルと分割先の一致を確認します。成功時は画像件数と元画像グループ件数を出力します。
エラーは標準エラー出力へ示し、終了コード1を返します。

派生画像は新しい `image_id` と画像ハッシュを持ち、`source_image_id` と `source_sha256` で元画像を参照します。
元画像が同じ台帳内にある場合は、参照ハッシュ、グループ、ラベル、分割先、加工履歴の継承を照合します。
派生画像のみの台帳も利用できます。その場合は元画像の実体を検証できないため、参照情報の形式だけを確認します。

## 再現可能な分割

```sh
uv run python -m detecter.ledger split data/ledger.jsonl \
  --seed 20260922 --evaluation-fraction 0.2 \
  --holdout-generator generator-a --holdout-camera camera-a \
  --output data/split-ledger.jsonl
```

`--holdout-generator` と `--holdout-camera` は任意で、複数回指定できます。
指定名が台帳にない場合は失敗します。指定名を含む元画像グループ全体を最終評価用の `evaluation` へ固定します。

その他の分割も元画像グループ単位です。シードとグループ名からSHA-256で順位を定め、
全グループ数に `--evaluation-fraction` を掛けて切り上げた件数を最終評価用へ割り当てます。
指定名による固定は、この割当てへ追加するため、最終評価用の比率が指定値を上回ることがあります。
残りは調整用の `tuning` です。台帳の行順に依存せず、同じ入力とシードから同じ結果を返します。
派生画像の枚数はグループ数に加算しません。

出力は元の行形式を保つJSON Linesです。画像パスは絶対パスになり、画像ID順に並びます。
既存の分割先は新しく計算した分割先へ変更します。入力ファイルと既存の出力ファイルは上書きしません。
`--output -` なら標準出力へ書きます。画像本体、ラベル、加工履歴は変更しません。

## 公開関数

`read_ledger(path, verify_files=True)` は検証済みの辞書のリストを返します。
`verify_files=False` はファイルの読取りとハッシュ照合だけを省略します。これは未計測画像を後続処理で
画像ごとに失敗記録として保存する用途であり、検証済み画像であることを意味しません。

`split_ledger(rows, seed=..., evaluation_fraction=0.2, holdout_generators=(), holdout_cameras=())`
は入力を変更せず、新しい行のリストを返します。正解ラベルは推論へ渡さず、台帳と評価処理だけで使います。
`main(argv)` はコマンドの入口です。共通CLIへの接続はIssue #11が担当します。

```sh
uv run python -m unittest discover -s tests -p test_ledger.py -v
```

テストは一時ディレクトリの小さな合成画像だけを使います。外部サービス、写真、GPUは不要です。
