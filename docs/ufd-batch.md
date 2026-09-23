# UFDの一括計測

```sh
uv run python -m detecter.ufd_batch --ledger data/ledger.jsonl --output results/ufd.jsonl --device cpu
uv run python -m detecter.ufd_batch --ledger data/ledger.jsonl --output results/ufd-tiles.jsonl --mode tiles
```

Issue #11のCLI統合後は `uv run detecter ufd-batch` でも同じ引数を使えます。
入力の相対画像パスは台帳の親ディレクトリ基準です。画像IDとSHA-256を照合し、
正解ラベル、分割先、生成器、撮影機器を推論へ渡しません。
取得・読込・画像の失敗は個別に記録し、残りの画像を続行します。失敗が1件でもあれば終了コードは1です。

既存UFDのモデル・キャッシュを再利用します。計測結果の再利用は行いません。
出力ファイルは新規作成だけに限定し、過去の計測を上書きしません。
記録にはUFDのソースコミット、判定層とCLIP重みのSHA-256、前処理版、実行環境を含めます。
単画像は既存のRGB・中央224画素切抜きです。分類器入力にはEXIF回転を適用します。
タイル実験は最大64枚の隙間のない分割、LANCZOS補間による224画素化、生スコア平均です。
画像の大きさに応じた実際のタイル数も保存し、単画像と異なる前処理版にします。
スコアは正しさの確率ではなく、判定境界の適用は別の処理です。
