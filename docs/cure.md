# CuReの計測

CuReは画像の生成痕跡を計測する公開モデルです。
この入口は画像1枚をCPU（既定）または`--device cuda`で処理し、
共有契約の計測記録をJSONで出力します。
画像を外部に送信しません。初回だけ公式の適合重み約25MBと、
初回だけ基盤モデル約2.7GBを取得します。

```sh
uv sync --extra cure --frozen
uv run --extra cure python -m detecter.cure image.jpg --image-id image-001 --device cpu --output -
```

共通CLIへの接続は `detecter cure` です。同じ引数を
`uv run --extra cure detecter cure`に指定できます。
`--output measurement.json`で保存先を指定できます。成功時は終了コード0、
失敗時は終了コード1です。画像のバイト列を読める場合は、形式や重みのエラーでも失敗記録に画像のハッシュを残します。
バイト列を読めずハッシュを計算できない場合だけ`sha256: null`です。

`raw_score`は公式推論の生成確率（2出力のソフトマックス）です。
スコアは正しさの確率ではありません。判定境界、正解ラベル、評価分割を推論に渡しません。
CuReを追加しても既定の判定設定や既定モデルは変わりません。

## 固定する実装

- 公式ソース: `manic-cui/CuRe`の`8f7832c83dcd3f4f89de955103e94a64ddc3cdc9`。
- 公式適合重み: 同リポジトリ`weights/cure_adapter.pt`の上記コミット版。
- 重みSHA-256: `17cabb334563c15abc8827db87dc272a4aef10f4279025faee1ef8d32c444ae1`。
- 基盤モデル: `facebook/PE-Core-L14-336`の`PE-Core-L14-336.pt`（約2.7GB）、
  revision `bafb0f76541d399057e980a25947f67acec76575`、SHA-256
  `0cdab5b338cbaa1e7a5dcd1b2fb4c9f4d5df1abd289564658edbab64a650e7e8`。
  `huggingface_hub`が指定revisionを取得します。到達できない場合は
  `--base-checkpoint`で同じハッシュの事前取得済みファイルを指定します。
- モデル構造: PE Core L/14視覚塔（336画素固定）にQ/V LoRA、
  128次元の応答部分空間、2出力の線形分類器。
- 前処理: RGB変換、デコード形式がPNGならJPEG品質96で再圧縮、最短辺390への3次補間、
  中央390画素の切り出し、336画素へ3次補間、JPEG品質70の再圧縮、
  平均0.5・標準偏差0.5による正規化、32ビット浮動小数点。
  EXIFの向き補正は公式推論と同じく行いません。

視覚塔の実装は公式の`cure/backbone.py`を固定解像度の推論用途に絞って同梱し、
`strict=True`で基盤重みと適合重みを統合して読み込みます。
適合重みが基盤重みを上書きする場合は失敗記録ではなく例外にします。
既存UFDの`torch==2.2.2`と`timm`等の版は変更しません。
公式の学習環境全体を再現するものではなく、実際の実行ライブラリを記録します。

キャッシュは`DETECTER_CACHE_DIR/cure/<ソース版>/`です。
環境変数を省略すると`~/.cache/detecter/`を使います。
`--cache-dir`でも親ディレクトリを指定できます。UFDのキャッシュには触れません。
キャッシュは毎回ハッシュを検査します。不一致時は自動上書きせず失敗記録を返します。
取得・読込の例外も失敗理由として保存します。

コードとモデルの利用条件は[THIRD_PARTY.md](../THIRD_PARTY.md)に記載しています。
