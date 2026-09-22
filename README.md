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

主な結果状態は次の4つです。

- `ai_evidence_confirmed`: 信頼済みC2PAにAI生成・編集の出典種別があります。
- `ai_likely`: UniversalFakeDetectの生スコアが暫定しきい値以上です。
- `inconclusive`: 必要な検査の一部を完了できませんでした。
- `no_ai_signal_detected`: 今回の検査ではAIを示す信号を確認できませんでした。

暫定しきい値 `0.5` はUniversalFakeDetectの公開コードに合わせた値です。対象画像で調整していないため、サービスの判断基準には使いません。

## 確認

```sh
uv run python -m unittest discover -s tests -v
```

## 出典

依存する研究実装とライセンスは [THIRD_PARTY.md](THIRD_PARTY.md) に記載しています。
