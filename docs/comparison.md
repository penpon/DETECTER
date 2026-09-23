# 同じ画像群のモデル比較

```sh
uv run --extra community-forensics python -m detecter.comparison community-forensics ufd \
  --ledger data/ledger.jsonl --output results/model-comparison.jsonl
```

CuReを含める場合は3件とも指定します。

```sh
uv run --extra community-forensics --extra cure python -m detecter.comparison community-forensics ufd cure \
  --ledger data/ledger.jsonl --output results/model-comparison.jsonl
```

Issue #11のCLI統合後は `uv run --extra community-forensics detecter compare` に同じ引数を指定します。
元ファイルの同一ID・ハッシュ集合を各モデルへ渡し、画像1枚ごとに独立した2行
（CuReありは3行）を保存します。
一方が失敗しても、もう一方の計測は続けます。失敗理由、期待したハッシュ、実際のハッシュを保存します。
画像を読めない場合でも期待した画像ID・ハッシュを保持します。

画像IDで順序を固定します。各モデルを1回読み込み、画像ごとの再読込を避けます。
Community ForensicsはCPU、UFDは `--device`、CuReは `--cure-device` で選択した機器を使います。
`--adapter-checkpoint` と `--base-checkpoint` で事前取得の重みを指定できます。
モデル版、重み版、前処理版、機器・ライブラリの版、派生元ID・ハッシュ、加工履歴を保存します。
推論関数へ正解ラベル、分割先、生成器、撮影機器を渡しません。
スコア平均、多数決、統合判定は作りません。後続の評価ではモデルごとに記録を選択してください。
出力は新規ファイルだけに保存します。どちらか1件でも失敗した場合、終了コードは1です。
CuReを指定しない従来の2件比較の出力は変わりません。
