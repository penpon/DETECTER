# DETECTER

GPT Image、Nano Banana、Midjourneyを中心に、画像の来歴情報と既存の学習済み検知器を確認する技術検証です。

現段階の判定は実験結果です。「AIを示す信号を確認できない」は、実写の証明ではありません。UniversalFakeDetectの出力値は、正しさの確率として表示しません。

## 含むもの

- ネットワークへ接続せずに行うC2PA読み取り・署名検証
- UniversalFakeDetectの公開済みモデルによる生スコア
- 画像ごとのJSON Lines記録
- JPEG、PNG、WebPの入力検証

追加学習、公式外部透かし検証、Web画面、管理画面、Paperspace配備はまだ含みません。

## 準備

Python 3.11と[uv](https://docs.astral.sh/uv/)を使います。

```sh
uv sync
```

UniversalFakeDetectを初めて実行すると、固定した公式コミットのソース約1.6MBと、CLIP ViT-L/14のモデルファイルをダウンロードします。以後はキャッシュを使います。Paperspaceでは `DETECTER_CACHE_DIR=/storage/detecter-cache` を指定すると、再起動後もモデルを再利用できます。

## 実行

画像または画像を含むディレクトリを指定します。ディレクトリは再帰的に確認します。

```sh
uv run detecter analyze path/to/image.jpg
uv run detecter analyze path/to/images --device cpu
```

結果は標準出力に表示し、既定では `results/detections.jsonl` に追記します。保存しない場合は `--output -` を指定します。

```sh
uv run detecter analyze image.png --output results/trial.jsonl
```

C2PAだけを確認する場合は、重い画像モデルを読み込みません。

```sh
uv run detecter analyze image.png --skip-ufd --output -
```

C2PAの署名が暗号学的に有効な場合は `Valid`、指定した信頼アンカーまで検証できた場合は `Trusted` として区別します。信頼アンカーは自動取得しません。

```sh
uv run detecter analyze image.jpg \
  --c2pa-trust-anchors path/to/anchors.pem \
  --skip-ufd --output -
```

## Jev比較実験

`--jev-compare` は、UniversalFakeDetectの全域タイル結果をJev 1.13へ送り、32×32量子化RGBグリッドを追加した条件との差をJSON Linesへ記録します。Jevは画像を受け取らず、送信するstateからファイル名、パス、SHA-256、正解ラベル、既存判定を除外します。1回の実行は最大4論理画像、8 APIリクエストです。

```sh
TYPESAFE_API_KEY='op://…' op run -- \
  uv run detecter analyze samples/generated samples/real/photo.jpg \
  --jev-compare --jev-derived-jpeg-of samples/real/photo.jpg \
  --output results/jev-comparison.jsonl
```

`--jev-derived-jpeg-of` の加工版は、EXIF回転を適用し、長辺を1024px、JPEG品質75で一時生成します。結果の記録後に削除します。`TYPESAFE_API_KEY` は環境から読み取り、コードやJSON Linesへ保存しません。`--jev-compare` では `--skip-ufd` を使用できません。

主な結果状態は次の4つです。

- `ai_evidence_confirmed`: 信頼済みC2PAにAI生成・編集の出典種別があります。
- `ai_likely`: UniversalFakeDetectの生スコアが暫定しきい値以上です。
- `inconclusive`: 必要な検査の一部を完了できませんでした。
- `no_ai_signal_detected`: 今回の検査ではAIを示す信号を確認できませんでした。

暫定しきい値 `0.5` はUniversalFakeDetectの公開コードに合わせた値です。対象画像で調整していないため、サービスの判断基準には使いません。

## DiffusionGemmaの画像入力比較

`scripts/compare_diffusiongemma.py` はCodivのOpenJevを使い、生成画像2枚とSony・iPhoneのカメラ写真2枚を比較します。各画像について「画像だけ」「画像＋既存のC2PA・UFD検査結果」を各1回実行します。計8リクエストで、再試行とサーバー側の自動追加サンプルは無効です。

```sh
uv run python scripts/compare_diffusiongemma.py --dry-run
CODIV_API_KEY='op://…' op run -- \
  uv run python scripts/compare_diffusiongemma.py
```

送信先は `https://api.codiv.ai/v1/systemone`、モデルは `openjev-0.1` です。4枚とも縮小せず、EXIF回転を適用してJPEG品質85へ再圧縮します。GPSなどの付随情報は除去します。この実験では画像自体が外部へ送られます。両条件は同じ再圧縮画像を使い、追加の検査結果は元ファイルの測定値です。元ファイルと既存記録のSHA-256が一致する場合だけ再利用します。

結果は `results/diffusiongemma-<実行ID>.jsonl` に記録します。画像の送信内容はハッシュと変換条件で記録し、画像のBase64やAPIキーは記録しません。`--output` で保存先を指定できますが、既存ファイルは上書きしません。8回の小規模な比較であり、前回のJev実験とはモデル・質問・画像の表現が異なります。

## 確認

```sh
uv run python -m unittest discover -s tests -v
```

## 出典

依存する研究実装とライセンスは [THIRD_PARTY.md](THIRD_PARTY.md) に記載しています。
