# reflex と vLLM structured reads の画像入力調査

reflex は画像に対する選択式の質問を実行できます。ただし、今回確認した公開資料には、AI 生成画像とカメラ写真を区別する検出性能の実証は見つかりませんでした。画像入力の実装、推奨設定、画像テスト、公開実験一覧を確認した結論です。[reflex-images (2026/09), 38–75 行][reflex-stable (2026/09), 1–26 行][reflex-image-tests (2026/09), 19–98 行][reflex-results (2026/09), 22–44 行]

調査日は 2026-09-22 です。GitHub の確認対象は `e21b3b23afdfeee7021a6604fa38f57e7ff5187f` に固定しました。以下は資料と実装の確認結果です。推論の実行、重みのダウンロード、追加インストールは行っていません。

## 画像入力と実行経路

- `POST /v1/systemone` の入力中の `state` に、`type` が `image`、`source` がファイルパス・HTTP URL・Base64 のデータ URI であるオブジェクトを置けます。実装は画像を読み込み、RGB の画素へ変換します。[reflex-serving (2026/09), 16 行][reflex-images (2026/09), 24–75 行]
- 標準の Transformers 経路は、画像とテキストを処理器へ渡し、その入力をモデルへ渡します。画像の説明文だけを評価する実装ではありません。[reflex-engine (2026/09), 395–418 行]
- 外部の推論サーバーを使う SGLang 経路は画像を受け付けません。画像を含む `state` に対して `NotImplementedError` を返します。画像を使う場合は標準の Transformers 経路が必要です。[reflex-sglang (2026/09), 160–166 行][reflex-serving (2026/09), 202–206 行]
- 画像の実行例が尋ねる内容は、被写体、文字の有無、職場で表示できる内容か、画質、説明文との一致です。AI 生成画像の検出例ではありません。[reflex-image-example (2026/09), 11–45 行]

## モデルと確率の意味

- 推奨設定は、画像と文章を扱う公開モデル `Qwen/Qwen3.5-4B` を追加学習せずに使います。追加学習用のアダプターと確率補正ファイルはいずれも未指定です。選択肢の順序を 2 通りに変えた結果を平均します。[Qwen3.5-4B (2026/03), Model Overview][reflex-stable (2026/09), 3–8 行]
- `kshetrajna12/reflex-qwen3.5-4b-lora` という追加学習済みアダプターは公開されています。ただし、モデル説明には一般用途では推奨設定に置き換えられたと明記されています。学習データの説明は、問い合わせ分類、文章の有害性、回答の根拠確認などが中心です。[reflex-adapter (2026/09), Status / How it was trained]
- 出力の `probabilities` は、候補の回答に対応するモデル内部の値を正規化したものです。推奨設定には対象画像で学習した確率補正は含まれません。作者も、確率の補正に使ったデータの性質が変わると補正は移転しないため、用途に合った正解付きデータで確認するよう説明しています。[reflex-readout (2026/09), 24–58・75–90 行][reflex-stable (2026/09), 4–5 行][reflex-readme (2026/09), 237–253 行]
- `confidence` は、確率が特定の選択肢へ集中する程度です。実装は「1 − 正規化したエントロピー」を使います。`confidence` を、その判定が正しい確率と同一視する根拠はありません。[reflex-readout (2026/09), 61–72・93–116 行]

## 検証で分かっている範囲

推奨設定の選定に使った外部データは、問い合わせ分類、文章間の関係、有害なチャット、店舗評価です。画像の生成元を識別する評価ではありません。公開画像テストは赤い円と青い四角を描いた画像を使い、図形の認識と、通常の計算方法との結果の一致を検証しています。したがって、これらの成績だけでは生成画像検出の精度や誤判定率を確定できません。[reflex-stable (2026/09), 10–25 行][reflex-image-tests (2026/09), 19–98 行]

## 実行環境の記載

配信手順は、重みが約 9 GB の構成に対して、GPU メモリ 16 GB 以上の NVIDIA CUDA 環境を案内しています。README の開始手順には 8 GB でも足りるという記載があり、資料間に差があります。機材を選ぶ際には配信手順側の 16 GB 以上を基準にするのが妥当です。Mac の説明は Apple Silicon 向けです。[reflex-serving (2026/09), 11–18 行][reflex-readme (2026/09), 86–94・201–217 行]

ブラウザー版は小型の Qwen3.5-0.8B を使用します。作者は、判断品質を確認する用途ではなく、仕組みを示すデモとして位置づけています。[reflex-readme (2026/09), 60–68 行]

## vLLM PR #57250 の確認結果

vLLM はモデルを動かす推論ソフトウェアです。この提案は、Google の画像対応モデル DiffusionGemma を使い、Jev と同じ形式の選択式回答を返す試作サーバーを追加します。2026-09-22 の確認時点で PR は未マージです。ただし、同日 04:20 UTC の LucasWilkinson によるレビューは正式に APPROVED であり、レビュー集計も APPROVED です。再確認時の状態は MERGEABLE / BLOCKED で、CI の一部に失敗があります。承認済みという進捗を含めて評価すべきであり、未マージという事実だけでは採用見通しを説明できません。マージ日時は未確定です。以下の実装確認は PR のコミット `f792b826f52f742a30c0cc99261df14e933818a6` に固定しています。[vllm-pr (2026/09), Purpose / PR status][vllm-approval (2026/09), review state][DiffusionGemma (2026/09), Introduction]

`POST /v1/systemone` へ画像ファイルを multipart 形式で添付するか、JSON の `images` に画像データ URI を渡せます。サーバーは画像を画像入力部へ渡す形式に変換し、文章の state と一緒にモデルへ送ります。画像の数値一覧を文章として読ませる方式ではありません。[vllm-readme (2026/09), 45–59 行][vllm-server (2026/09), 1110–1157・1312–1315 行]

PR に掲載された画像評価は色、四角の数、位置、存在、明暗差の認識です。そこには AI 生成画像とカメラ写真の識別精度は示されていません。画像入力の成立と、画像の生成元を判定する性能の実証は区別する必要があります。[vllm-pr (2026/09), Additional Results]

このサーバーの `confidence` は、選ばれた候補の最大確率です。reflex の確率分布の集中度とは計算式が異なるため、同名の数値をそのまま比較することはできません。両者とも、確認した資料から画像の生成元を判定する正答率へ読み替える根拠は得られません。[vllm-server (2026/09), 982–988・1164–1169 行][reflex-readout (2026/09), 61–72 行][vllm-pr (2026/09), Additional Results][reflex-image-tests (2026/09), 19–98 行]

作者の実行例は DGX Spark 上の DiffusionGemma 26B-A4B NVFP4 構成です。画像入力関連の修正 PR #57589 は 2026-09-21 にマージされています。古いコメントの画像入力エラーを、そのまま現在の実装の状態とは扱えません。[vllm-pr (2026/09), Test Plan / Test Result][vllm-vision-fix (2026/09), PR status]

## 出典

[vllm-pr, 2026/09] mmastrac. “[Core] structured generation mode for DiffusionGemma model (Jev-like).” GitHub. https://github.com/vllm-project/vllm/pull/57250

[vllm-approval, 2026/09] LucasWilkinson. “Approval review for PR #57250.” GitHub. https://github.com/vllm-project/vllm/pull/57250#pullrequestreview-5274106659

[vllm-readme, 2026/09] mmastrac. “Structured reads on DiffusionGemma.” GitHub. https://github.com/mmastrac/vllm/blob/f792b826f52f742a30c0cc99261df14e933818a6/examples/features/structured_diffusion/README.md

[vllm-server, 2026/09] mmastrac. “structured_server.py.” GitHub. https://github.com/mmastrac/vllm/blob/f792b826f52f742a30c0cc99261df14e933818a6/examples/features/structured_diffusion/structured_server.py

[vllm-vision-fix, 2026/09] vLLM contributors. “[Bugfix] DiffusionGemma: fix multimodal support.” GitHub. https://github.com/vllm-project/vllm/pull/57589

[DiffusionGemma, 2026/09] Google DeepMind. “DiffusionGemma 26B-A4B-it.” Hugging Face. https://huggingface.co/google/diffusiongemma-26B-A4B-it

[reflex-images, 2026/09] kshetrajna12. “src/reflex/images.py.” GitHub. https://github.com/kshetrajna12/reflex/blob/e21b3b23afdfeee7021a6604fa38f57e7ff5187f/src/reflex/images.py#L24-L75

[reflex-engine, 2026/09] kshetrajna12. “src/reflex/engine.py.” GitHub. https://github.com/kshetrajna12/reflex/blob/e21b3b23afdfeee7021a6604fa38f57e7ff5187f/src/reflex/engine.py#L395-L418

[reflex-sglang, 2026/09] kshetrajna12. “src/reflex/backends/sglang.py.” GitHub. https://github.com/kshetrajna12/reflex/blob/e21b3b23afdfeee7021a6604fa38f57e7ff5187f/src/reflex/backends/sglang.py#L160-L166

[reflex-image-example, 2026/09] kshetrajna12. “examples/image_triage.py.” GitHub. https://github.com/kshetrajna12/reflex/blob/e21b3b23afdfeee7021a6604fa38f57e7ff5187f/examples/image_triage.py#L11-L56

[reflex-stable, 2026/09] kshetrajna12. “serving/stable.json.” GitHub. https://github.com/kshetrajna12/reflex/blob/e21b3b23afdfeee7021a6604fa38f57e7ff5187f/serving/stable.json

[reflex-image-tests, 2026/09] kshetrajna12. “tests/test_engine_vl_gpu.py.” GitHub. https://github.com/kshetrajna12/reflex/blob/e21b3b23afdfeee7021a6604fa38f57e7ff5187f/tests/test_engine_vl_gpu.py#L19-L98

[reflex-results, 2026/09] kshetrajna12. “Results: everything we tried, in the order we tried it.” GitHub. https://github.com/kshetrajna12/reflex/blob/e21b3b23afdfeee7021a6604fa38f57e7ff5187f/docs/results/README.md

[reflex-readout, 2026/09] kshetrajna12. “src/reflex/readout.py.” GitHub. https://github.com/kshetrajna12/reflex/blob/e21b3b23afdfeee7021a6604fa38f57e7ff5187f/src/reflex/readout.py#L24-L116

[reflex-serving, 2026/09] kshetrajna12. “Serving reflex for evaluation.” GitHub. https://github.com/kshetrajna12/reflex/blob/e21b3b23afdfeee7021a6604fa38f57e7ff5187f/docs/SERVING.md

[reflex-readme, 2026/09] kshetrajna12. “reflex.” GitHub. https://github.com/kshetrajna12/reflex/blob/e21b3b23afdfeee7021a6604fa38f57e7ff5187f/README.md

[reflex-adapter, 2026/09] kshetrajna12. “reflex: a System One decision model (LoRA for Qwen/Qwen3.5-4B).” Hugging Face. https://huggingface.co/kshetrajna12/reflex-qwen3.5-4b-lora/blob/9df1cbbbc1837ba494530a59d3d9d345688ed250/README.md

[Qwen3.5-4B, 2026/03] Qwen. “Qwen3.5-4B.” Hugging Face. https://huggingface.co/Qwen/Qwen3.5-4B/blob/851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a/README.md
