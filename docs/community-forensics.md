# Community Forensics 384の計測

Community Forensicsは画像の生成痕跡を計測する公開モデルです。
この入口は画像1枚をCPUで処理し、共有契約の計測記録をJSONで出力します。
画像を外部に送信しません。初回だけ公式の重み約87.3MBを取得します。

```sh
uv sync --extra community-forensics --frozen
uv run --extra community-forensics python -m detecter.community_forensics image.jpg --image-id image-001 --device cpu --output -
```

共通CLIへの接続はIssue #11が担当します。接続後は同じ引数を
`uv run --extra community-forensics detecter community-forensics`に指定できます。
`--output measurement.json`で保存先を指定できます。成功時は終了コード0、
失敗時は終了コード1です。画像が存在する場合、失敗記録にも画像のハッシュを残します。
画像自体を読めない場合は`sha256: null`です。

`raw_score`は公式分類器の出力値（シグモイド関数適用前）です。
スコアは正しさの確率ではありません。判定境界、正解ラベル、評価分割を推論に渡しません。

## 固定する実装

- 公式ソース: `JeongsooP/Community-Forensics`の`ee5b71d43db0f3779e1edd64ee927b13f2dd6ad4`。
- 公式重み: `OwensLab/commfor-model-384`の`6076002bf0d9dd37537f965ee2f06f826c333b61`。
- 重みSHA-256: `b89f36275f3bf5e2b040eee36597a8f19db051bff9a473a9cf7b2466284fb387`。
- モデル構造: `timm==1.0.15`の`vit_small_patch16_384.augreg_in21k_ft_in1k`、出力1個。
- 前処理: RGB変換、短辺440への双線形補間、中央384画素の切り出し、
  0〜1への変換、ImageNetの平均・標準偏差による正規化、32ビット浮動小数点。
  EXIFの向き補正を行います。前処理版`exif-v2`に識別して記録します。

公式の`ViTClassifier`は同じモデルを`vit`という属性に保持しています。
この実装は重み名の`vit.`を除き、全パラメータの一致を厳密に検査して読み込みます。
直後に全置換されるImageNetの重みを二重取得しません。
既存UFDの`torch==2.2.2`と`torchvision==0.17.2`は変更しません。
公式の学習環境全体を再現するものではなく、実際の実行ライブラリを記録します。

キャッシュは`DETECTER_CACHE_DIR/community-forensics-384/<重み版>/`です。
環境変数を省略すると`~/.cache/detecter/`を使います。
`--cache-dir`でも親ディレクトリを指定できます。UFDのキャッシュには触れません。
キャッシュは毎回ハッシュを検査します。不一致時は自動上書きせず失敗記録を返します。
取得・読込の例外も失敗理由として保存します。

## 分離した公式数値一致確認

```sh
uv run --extra community-forensics python scripts/verify_community_forensics.py
```

この確認だけはネットワークと実際の重みを使います。公式ソースのSHA-256を検査し、
推論に使うクラスと関数を変更せず実行します。学習専用の依存関係は読み込みません。
全パラメータを置換する前のImageNet重み取得だけを省略します。
3枚の合成画像（RGB、透過付きRGB、白黒）について、前処理結果の完全一致と、
公式モデル出力との絶対許容誤差`1e-5`・相対許容誤差`1e-5`以内を確認します。
通常の`unittest`は小さい合成画像とモデル・ネットワークの代替を使います。

コードとモデルの利用条件は[THIRD_PARTY.md](../THIRD_PARTY.md)に記載しています。
