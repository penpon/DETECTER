# AI生成画像検知の推奨構成と専用モデルの実装候補

現時点で試す第一候補は Community Forensics です。公開重みとコードの利用条件が明確で、複数の未学習生成器と画像加工に対する評価が公開されているためです。ただし、作者自身が重要用途では誤り率がまだ高いと説明しています。単独で真偽を確定する用途への推薦ではありません。[Community 論文 (2025/06), §3.4・§4.4・Limitations][Community モデル (2025/08), license][Community コード (2025), LICENSE]

確認日は 2026-09-22 です。以下の 3 件について、作者の論文、公式コード、重みの配布案内を確認しました。網羅的な最新順位の比較ではありません。重みのダウンロード、推論、学習は実行していません。

## Community Forensics：商用利用を含む試作の第一候補

Community Forensics は、多数の生成器から収集した画像を学習に使う専用検知器です。学習・評価用データの総体は 4,803 モデル由来の約 270 万枚です。この数は独立した生成方式の数ではありません。著者も Stable Diffusion 系への偏りを認めています。[Community 論文 (2025/06), Abstract・§3・Limitations]

- **重みと利用条件：** 224 ピクセル入力版と 384 ピクセル入力版が公式 Hugging Face に公開されています。384 版のモデル説明は MIT ライセンスを明記しています。コードも MIT です。MIT の条件で必要な著作権表示・ライセンス表示は維持する必要があります。学習データまで同一条件で再利用できるという意味ではありません。[Community README (確認 2026/09), Usage Examples][Community モデル (2025/08), license][Community コード (2025), LICENSE][Community 論文 (2025/06), §3.4]
- **入力処理：** 公式例は独自の `CommForImageProcessor` と `ViTClassifier` を使います。評価時の処理は縮小・拡大、中央部分の切り出し、画素値の正規化です。224 版と 384 版を取り違えず、公式の前処理を再現する必要があります。[Community 前処理 (確認 2026/09), 17–44 行][Community データ処理 (確認 2026/09), 281–311 行]
- **評価された生成器：** 未学習の生成器を含む評価では DALL·E 2/3、Ideogram V1/V2、Midjourney V5/V6、Firefly Image 2/3、FLUX.1-dev/schnell、Imagen 3 を扱っています。これは論文で列挙された版に対する評価です。[Community 論文 (2025/06), §3.2・§3.4]
- **画像加工への評価：** JPEG 圧縮、ぼかし、回転、サイズ変更、余白追加、せん断変形を評価しています。学習時にも複数の加工を順序を変えて適用します。[Community 論文 (2025/06), §4.1・§4.4・Figure 7]
- **限界：** 論文の評価集合では、モデルが出した値を任意の本番画像の「AI 生成である確率」と保証していません。作者は重要用途に対する誤り率の高さを明記しています。また、中央切り出しによる入力だけで画像全域の部分生成を検出できるという実証は、今回確認していません。[Community 論文 (2025/06), Limitations][Community データ処理 (確認 2026/09), 304–311 行]

## B-Free：圧縮・縮小の比較実験に有用ですが、公開版は非営利限定

B-Free は実写と、それに内容を合わせて生成した画像を学習に使います。画像内容や保存形式の違いだけに依存する学習を抑える設計です。画像表現モデル DINOv2 を基礎にした分類器を使います。[B-Free 論文 (2025/04), §3][B-Free README (確認 2026/09), Training Paradigm・Architecture]

- **重みと利用条件：** 公式サイトから `BFREE_dino2reg4.zip` を取得できます。しかし、公式ライセンスは情報提供・非営利用途に限定し、無許可の産業・営利用途を明示的に禁止しています。商用サービスの既定構成には、そのまま採用できません。商用利用には権利者による別の許諾が必要です。[B-Free 推論 (確認 2026/09), Pre-trained weights][B-Free ライセンス (2025), Terms and Conditions]
- **入力処理：** 504 × 504 ピクセルの部分画像を使い、大きな画像は複数箇所の結果を平均します。公開実装は特徴マップの中央と四隅の 5 箇所を処理します。入力を一律に小さくする独自前処理は、公開手順と一致しません。[B-Free README (確認 2026/09), Architecture][B-Free 切り出し (確認 2026/09), 37–57 行]
- **評価された生成器・加工：** DALL·E 2/3、Midjourney、Firefly、FLUX、Stable Diffusion 3.5 などを含む評価があります。JPEG 圧縮、サイズ変更、ぼかしを評価しています。追加実験では、サイズを 0.7～1 倍、JPEG 品質値を 70～100 にする条件も調べています。この範囲が、任意の SNS 再圧縮への保証になるわけではありません。[B-Free 論文 (2025/04), §4・§5・Appendix F]
- **2026 年の更新：** 公式 README は 2026-01-14 に新しい生成器のデータセットを公開したと記載しています。その内容は FLUX と Stable Diffusion 3.5 の各 1,000 枚です。2026 年版の新しい検知モデルを公開したという記載ではありません。[B-Free README (確認 2026/09), News・Dataset of new generators]
- **限界：** 学習で使った生成方式は Stable Diffusion 2.1 です。著者は、全く異なる生成方式が登場すれば失敗する可能性が高いことと、敵対的な画像変更への弱さを明記しています。公開コードにはバッチ処理がまだないという記載もあります。[B-Free 論文 (2025/04), §6][B-Free 推論 (確認 2026/09), Inference from csv]

## AIDE：異なる特徴を組み合わせる比較候補

AIDE は、画像の意味的な特徴に加え、細かな画素変化から取り出した特徴を統合する検知器です。精巧な生成画像を集めた Chameleon という評価データも公開しています。[AIDE 論文 (2025/02), §3・§4]

- **重みと利用条件：** 公式 README に Google Drive の重み配布リンクがあります。コードは MIT です。一方、Chameleon データセットは学術研究限定で、商用利用は禁止されています。配布重み固有の商用ライセンスは今回の資料では確認できませんでした。コードの MIT 表示だけで、重みとデータの条件も同一とは判断できません。[AIDE README (確認 2026/09), Chameleon・Model Zoo][AIDE コード (2024), LICENSE]
- **入力処理：** 周波数変換で細かな変化の強い部分と弱い部分を選びます。選んだ 4 部分と画像全体をそれぞれ 256 × 256 ピクセルにし、複数の経路で処理します。一般的な画像分類器へ縮小画像を 1 枚渡すだけの入力とは異なります。[AIDE 論文 (2025/02), §4・§5.1][AIDE データ処理 (確認 2026/09), 176–198 行]
- **圧縮への評価：** JPEG 品質値 95・90・75・50 とぼかしを評価しています。全方式で性能が低下すると報告しています。今回確認した資料では、Community Forensics や B-Free と同程度に明示されたサイズ変更の評価は確認できませんでした。[AIDE 論文 (2025/02), §5.3・Table 6]
- **限界：** 既存ベンチマークで良い結果でも、精巧な生成画像を集めた Chameleon では AIDE 自身の性能も低いと著者が明記しています。実利用を想定した画像で別途確認する重要性を示す比較候補です。[AIDE 論文 (2025/02), §5.2・Appendix C]

## 選定上の判断と未確認点

以下は資料からの引用ではなく、今回の導入判断です。まず Community Forensics 384 版を基準にします。B-Free は非営利の比較実験、または商用許諾が取れた場合の候補です。AIDE は公開重みの条件を確認したうえで、異なる誤り方をするか比較する候補です。

3 件を単純多数決にすれば安定するという証拠は、今回の調査では確認できません。導入時には同じ画像群で比較し、実写を誤って生成画像と判定する割合と、生成画像を見逃す割合を別々に測る必要があります。生成器の版、実写の撮影機器、JPEG 圧縮、縮小、スクリーンショット、部分的な生成編集など、運用上の条件ごとに測ることを提案します。判定が不安定な画像を保留する条件も、この評価で決めます。

今回の一次資料からは、2026-09-22 時点の最新商用生成器を網羅する検出性能を確認できませんでした。公開年が新しいことや、既存ベンチマークの順位だけを理由に、本番用途の信頼性が高いとは結論しません。

## 来歴情報と公式透かしの確認結果

C2PAは画像の生成・編集履歴を署名付きで記録する規格です。C2PAの有無だけから実写か生成画像かを決める規格ではありません。署名者の信頼、記録の完全性、対象画像との結び付き、生成・編集の出典属性を区別します。来歴情報が存在しない画像を、その理由だけで信用できないと判断すべきではないと説明されています。[C2PA Explainer (確認 2026/09), §2・§7.1.2・§7.4.4]

Googleの公式案内では、ログイン済みのGeminiアプリへ画像を渡すとSynthIDという不可視の透かしを確認できます。検出はGoogleのAIによる生成・編集への関与を示します。検出されなくても、他社の生成AIや、検出不能な変更・小さな編集を排除できません。これは一般的な画像モデルによる見た目の推測とは異なる機能です。公開案内では画像検証は24時間の移動窓あたり約10回であり、大量処理の無制限APIとしては扱いません。[Gemini検証ヘルプ (確認 2026/09), About the verification results・Common questions about SynthID]

## 評価研究から分かること

AIGIBenchは、11種類の検知器について未知の生成元、劣化、学習時の加工、推論前の画像処理を比較しています。実際に流通する画像では公開設定の高精度が維持されないことを報告し、実写側の正解率と生成画像側の検出率を分けて評価しています。評価された商用生成器にはImagen 3、DALL·E 3、Midjourney V6などが含まれます。論文中のGemini利用は画像説明の生成であり、最新Gemini生成画像を検出できたという根拠ではありません。[AIGIBench (2025/10), Abstract・§2.3・§3.2・§3.4]

Fake or JPEG? は、実写と生成画像の保存圧縮や寸法の偏りを検知器が学習してしまう問題をGenImage上で評価しています。これは今回のUFDやDiffusionGemmaの誤り原因を特定する結果ではありません。画像内容、保存形式、入手元などを区別して評価する必要性の根拠として参照します。[Fake or JPEG? (2024/03), Abstract・Experiments・Conclusion]

## DETECTERへの推奨構成（本調査に基づく提案）

ここからは、このプロジェクトへの設計提案です。文献の成績をそのまま達成できるという主張ではありません。専用検知器の追加実行・学習はまだ行っていません。

1. **判定対象を決めます。** 最初の対象を「画像全体が生成されたもの」に絞ります。「カメラ写真の通常現像・HDR・ノイズ除去」と「生成AIによる部分置換」は別ラベルとして管理します。AI技術が少しでも関わればすべてAI画像とする定義では、スマートフォン写真や編集済み写真との境界が曖昧になります。元の実験の質問は生成と編集を一括していました。[ローカル実験 (2026/09), 解釈の限界]
2. **元ファイルの検証を先に行います。** 元バイト列を保持してC2PAを読みます。信頼する署名者・有効な署名・画像との対応確認・AI出典属性が揃った場合は「信頼する署名者によるAI出典を確認」と表示します。ハッシュ不一致や未検査をAIの証拠へ置き換えません。Google由来の可能性がある画像では、利用可能な公式SynthID検証を独立した証拠として加えます。[C2PA Explainer (確認 2026/09), §2・§7.4.4][Gemini検証ヘルプ (確認 2026/09), About the verification results]
3. **専用検知器を一つ追加します。** Community Forensics 384版を、公式の入力処理と固定した重みで比較します。既存UFDは比較用に残します。最初から多数決にはせず、実写の誤検知が減り、生成画像の検出率が上がるかを見ます。別モデルの追加は、独立した最終評価で増分の効果がある場合に限ります。必要なら、複数のスコアを入力とする小さな分類器を調整用データで学習します。相関するスコアを独立な確率として掛け合わせません。
4. **入力処理を固定します。** 元画像を保持し、モデルごとに作者の縮小・切り出し・正規化を再現します。独自の64タイル方式や、最大タイルスコアだけでの判定は、画像単位の誤検知率を測ってから採用します。同じ検知器の64タイルは独立した64台の検知器ではありません。API送信のための再圧縮と検知器用入力も記録上区別します。
5. **判定境界を実測で固定します。** 専用検知器の生スコア0.5、または言語モデルのconfidenceだけで基準を決めません。調整用データで判定境界を決めた後、未使用の画像で実写誤検知率・生成画像検出率・保留率を測ります。確率の補正は数値の解釈を整える処理であり、識別できない画像を識別可能にする保証ではありません。
6. **保留の基準を用意します。** 未評価の生成元・極端に小さい画像・検知器間の不一致・画像加工での判定反転などを保留候補にします。保留だけで誤検知率を良く見せないよう、全入力中の保留率と、保留を含めた生成画像の見逃しも報告します。JevやDiffusionGemmaは、採用するとしても説明や確認箇所の整理を担当させます。最終判定への追加は、同じ未使用画像で改善を確認できた場合に限定します。

### 評価データと採用基準の具体案

- 調整用と最終評価用を元画像単位で分割します。同じ画像のJPEG版・縮小版・切り抜き版を別の分割へ入れません。生成器の版や撮影機器を丸ごと評価側へ残す試験も設けます。
- 実写側にはSonyの高ISO・Lightroom現像・iPhone HDR・HEICからの変換・SNS再保存を含めます。生成側には出所が確認できるGPT Image・Nano Banana・Midjourneyの対象バージョンを含めます。生成履歴と画像ハッシュをローカルで管理し、正解ラベルは推論入力へ渡しません。
- 同じ後処理を実写・生成画像の双方に適用します。提案する初期条件は未加工、長辺1024/512px、JPEG品質95/85/75、切り抜き、スクリーンショットです。これらは今回の提案値で、論文の推奨値や達成済み条件ではありません。
- 初期の採用目標として「実写をAIと誤る割合0.1%以下」を置きます。この基準で生成画像の何%を拾えるかも同時に測り、検出率が用途に足りなければ採用しません。満たすことを保証した数値ではありません。
- 0.1%程度の低い誤検知率を主張するには、実写2枚では不足します。同じ対象母集団から独立に抽出した未使用実写3,000枚で誤検知0件の場合、二項分布による片側95%信頼上限は約0.0998%です。計算式は `1 - 0.05**(1/3000)` です。これはこの文書の計算例であり、将来の全画像や機器別の各群への保証ではありません。派生画像3,000枚を独立な元画像3,000枚として数えてはいけません。

### 最小の次の実装

まず、Community Forensics 384版の公式推論を独立した環境で動かし、現在の画像を固定の回帰確認に使います。その後、出所と処理履歴の分かる画像を増やし、UFDと同じ判定基準で比較します。Nano Bananaについては公式SynthID検証を別途記録します。C2PAは既存の検証経路を活用します。この段階では、新しい汎用画像モデル、多数決、追加学習をまとめて導入しません。

## 出典

[C2PA Explainer, 確認 2026/09] C2PA. “Explainer.” Specification 2.3. https://spec.c2pa.org/specifications/specifications/2.3/explainer/Explainer.html

[Gemini検証ヘルプ, 確認 2026/09] Google. “Verify AI-generated images, videos, and audio.” https://support.google.com/gemini/answer/16722517?hl=en

[AIGIBench, 2025/10] Ziqiang Li et al. “Is Artificial Intelligence Generated Image Detection a Solved Problem?” NeurIPS 2025 / arXiv v2. https://arxiv.org/html/2505.12335v2

[Fake or JPEG?, 2024/03] Patrick Grommelt, Louis Weiss, Franz-Josef Pfreundt, and Janis Keuper. “Fake or JPEG? Revealing Common Biases in Generated Image Detection Datasets.” arXiv v2. https://arxiv.org/html/2403.17608v2

[ローカル実験, 2026/09] DETECTER. “DiffusionGemmaによる画像入力比較.” [実験記録](results/diffusiongemma-summary.md)

[Community 論文, 2025/06] Jeongsoo Park and Andrew Owens. “Community Forensics: Using Thousands of Generators to Train Fake Image Detectors.” CVPR 2025 / arXiv v2, 2025-06-09. https://arxiv.org/html/2411.04125v2

[Community README, 確認 2026/09] Jeongsoo Park. “Community Forensics.” https://github.com/JeongsooP/Community-Forensics/blob/ee5b71d43db0f3779e1edd64ee927b13f2dd6ad4/README.md

[Community モデル, 2025/08] OwensLab. “commfor-model-384.” https://huggingface.co/OwensLab/commfor-model-384/blob/6076002bf0d9dd37537f965ee2f06f826c333b61/README.md

[Community コード, 2025] Jeongsoo Park. “LICENSE.” https://github.com/JeongsooP/Community-Forensics/blob/ee5b71d43db0f3779e1edd64ee927b13f2dd6ad4/LICENSE

[Community 前処理, 確認 2026/09] Jeongsoo Park. “dataprocessor_hf.py.” https://github.com/JeongsooP/Community-Forensics/blob/ee5b71d43db0f3779e1edd64ee927b13f2dd6ad4/dataprocessor_hf.py#L17-L44

[Community データ処理, 確認 2026/09] Jeongsoo Park. “dataloader.py.” https://github.com/JeongsooP/Community-Forensics/blob/ee5b71d43db0f3779e1edd64ee927b13f2dd6ad4/dataloader.py#L281-L311

[B-Free 論文, 2025/04] Fabrizio Guillaro et al. “A Bias-Free Training Paradigm for More General AI-generated Image Detection.” CVPR 2025 / arXiv v2, 2025-04-03. https://arxiv.org/html/2412.17671v2

[B-Free README, 確認 2026/09] GRIP-UNINA. “B-Free.” https://github.com/grip-unina/B-Free/blob/c6a9f898782fb466b29af01f21960b67415afb0e/README.md

[B-Free 推論, 確認 2026/09] GRIP-UNINA. “Pre-trained weights / Inference.” https://github.com/grip-unina/B-Free/blob/c6a9f898782fb466b29af01f21960b67415afb0e/code/README.md

[B-Free ライセンス, 2025] GRIP-UNINA. “LICENSE.txt.” https://github.com/grip-unina/B-Free/blob/c6a9f898782fb466b29af01f21960b67415afb0e/LICENSE.txt

[B-Free 切り出し, 確認 2026/09] GRIP-UNINA. “wrapper5crops.py.” https://github.com/grip-unina/B-Free/blob/c6a9f898782fb466b29af01f21960b67415afb0e/code/networks/wrapper5crops.py#L37-L57

[AIDE 論文, 2025/02] Shilin Yan et al. “A Sanity Check for AI-generated Image Detection.” ICLR 2025 / arXiv v3, 2025-02-15. https://arxiv.org/html/2406.19435v3

[AIDE README, 確認 2026/09] Shilin Yan. “A Sanity Check for AI-generated Image Detection.” https://github.com/shilinyan99/AIDE/blob/6725b710d5c437ab2f59792908ce0377dfc907de/README.md

[AIDE コード, 2024] Shilin Yan. “LICENSE.” https://github.com/shilinyan99/AIDE/blob/6725b710d5c437ab2f59792908ce0377dfc907de/LICENSE

[AIDE データ処理, 確認 2026/09] Shilin Yan. “data/datasets.py.” https://github.com/shilinyan99/AIDE/blob/6725b710d5c437ab2f59792908ce0377dfc907de/data/datasets.py#L176-L198
