# 劣化耐性AI画像検出器の小規模学習パイロット計画の妥当性検証

**調査基準日：2026年9月26日（JST）**

結論を先に述べると、**DCPT + So-Fake-Set を使った小規模パイロット自体は実施価値があるが、Issue #68 の現行案をそのまま走らせるのは推奨しません。** 最大の理由は、DCPT の「+9.1〜17.9pt」という数字が **低FPR性能ではなく Accuracy の改善**であり、AUC の改善ははるかに小さいこと、さらに現在の実写586群では **FPR≤0.1% を統計的に確認できない**ことです。DCPTの原論文は Synthbuster で平均劣化ACCを64.0%→73.1%に改善しましたが、同じ比較の平均AUCは78.5%→79.4%にとどまり、clean AUCは89.1%→87.9%へ低下しています。したがって、**「平均性能の改善」と「実写スコア分布の99.9パーセンタイルより上でのTPR改善」を同一視してはいけません。** citeturn30view1

一方で、So-Fake v5 は本計画にかなり好都合です。**GPT-Image-2、Nano Banana、Nano Banana 2 は So-Fake-Set には入っておらず、明示的に So-Fake-OOD 側へ隔離されています。** よって、So-Fake-Setだけを学習に使い、So-Fake-OODを学習・ハイパーパラメータ選択に使わなければ、今回の主要評価生成器に対する generator-OOD 条件を維持できます。 citeturn20view0turn30view0

## 仮説判定

| 仮説 | 判定 | 一言根拠 |
|---|---|---|
| **H1. DCPTはこの設定で機能する** | **一部成立** | 劣化耐性を改善する機序と独立したLPTの支持はある。ただしDCPTはACC/AUCのみで、**TPR@FPR≤1%/0.1%の報告なし**。+9〜18ptを低FPRへ外挿する根拠はない。 citeturn30view1turn27view4 |
| **H2. So-Fake-Setは学習データとして適切** | **一部成立** | 生成器分離は非常に良い。GPT-Image-2/Nano Banana系列はOOD側。ただしHFの「CC BY 4.0」表記だけでは上流画像権利を解決できず、CelebA/FFHQ等にはより強い制限がある。 citeturn19search0turn24search0turn24search2 |
| **H3. 小規模パイロットで有意な判断ができる** | **一部成立** | 学習方式の方向性判定は可能。ただし**586実写群ではFPR 0.1%を証明不能**。0 FPで95%片側上限≤0.1%には最低2,995独立実写群が必要。 |
| **H4. 劣化再現の内挿が効く** | **一部成立** | So-Fake/LPT双方が劣化適合の有効性を示す一方、LPT自身が**過度・不一致な劣化は性能を悪化**させると報告。実SNS伝送を別holdoutで持つ必要がある。 citeturn21view0turn27view5turn21view4 |
| **H5. SynthID優先度戦略は妥当** | **一部成立** | OpenAIとNano Banana系列では現在かなり有力。だが検出器・export path・時期依存で、`not_detected` は人間生成を意味しない。Nano Bananaの**あなたの実伝送条件での残存率**は未測定。 citeturn19search3turn22search3 |
| **H6. より単純な代替がない** | **不成立** | まず **So-Fake-R1公開モデルをGPUで直接評価、augmentation-onlyとの同条件比較、既存モデルの再較正**をやるべき。DCPTの増分価値はその後に判定可能。So-Fakeはコード・モデル・データ公開済み。 citeturn20view0 |

**総合判定は「計画を修正してGO」**です。特に重要なのは、DCPTを「本命モデル」ではなく、**同じデータ・同じ劣化を見せる augmentation-only / paired-CE に対する増分仮説**として検証することです。

## DCPTとLPTから実際に言えること

DCPT原論文の実験条件は、今回のユースケースよりかなり限定されています。バックボーンは **DINOv2 ViT-B/14 with registers を完全freeze**し、学習するのは `768→256→2` の197KパラメータMLPのみです。学習データは B-Free の 51,517 COCO real + 51,518 SD2.1 fake、評価は Synthbuster の9生成器×1,000画像とCOCO real 1,000枚です。劣化は JPEG Q30/50/70、Gaussian blur σ1/2/3、resize 0.5/0.25。20 epoch、batch 64、AMP、単一 RTX 4090D 24GB で学習しています。 citeturn26view3turn27view0

DCPTの学習ではclean/degradedの2 viewを作り、degraded側に JPEG `q∈{30,50,70,90}`、Gaussian blur、downsamplingを確率0.5で加えます。そして通常の分類CEに加え、特徴のcosine consistencyと予測分布のsymmetric KL consistencyを課します。推論時には通常の1 forwardだけなので、**追加推論コストがない**のは今回の用途にも明確な利点です。 citeturn26view3

ただし、報告された効果を読む際に最も重要なのは指標です。JPEG Q70ではACCが56.8→72.5、Q50で53.3→71.2、Q30で52.3→69.5、8劣化平均で64.0→73.1でした。一方、対応する平均AUCは78.5→79.4にしか上昇しておらず、clean AUCは89.1→87.9です。さらにJPEGだけを見ると、DCPT両lossの平均71.1より、prediction-consistency単独の72.9の方が高いというablationもあります。つまり「DCPT全部入りがあらゆる動作点で最適」とまでは原論文自身も示していません。 citeturn30view1

これは今回かなり重要です。**FPR 0.1%はROC曲線の極端な左端だけを見る問題**です。ACCは通常、分布中央付近のthreshold性能に強く支配され、AUCもROC全域の平均です。したがってDCPTで平均ACCが+9.1ptになっても、99.9パーセンタイル付近にいる `kind=unknown` のスクリーンショット実写群が一緒に高スコア化すれば、TPR@0.1% FPRはほとんど動かない可能性があります。**この部分は推測ですが、DCPTのAUC改善がACC改善より著しく小さいという結果は、そのリスクを無視できない根拠です。** citeturn30view1

また、原論文が比較対象として説明するB-Free自身はJPEG・blur・scaling augmentationを既に持っていますが、DCPT論文の直接比較用 frozen-backbone baseline については、「同一clean/degraded exposureをCEだけで学習したaugmentation-only arm」を独立した表としては提示していません。このため、あなたの実験では **「augmentationそのもの」と「consistency loss」を必ず分離して測る**必要があります。 citeturn31view0

LPTはこの点を独立に補強します。NTIRE 2026で3位となったLPTは、EVA-CLIPを基盤に、各visual transformer blockのMHSAとFFN linear layerへLoRAを挿入し、clean/degraded pairにCE + KL + feature MSEを課します。rank/scalingとも16、224×224、5 epochs、8×NVIDIA A800で、最終学習にはSo-FakeとChameleonも追加しています。 citeturn26view4turn27view3

LPTのpairwise ablationは、CE-onlyのpublic-test AUC 87.91から、KL追加で88.06、KL+MSEで89.26へ改善しており、**pairwise consistency自体には独立したプラスの証拠**があります。ただし改善幅は+1.35 AUCポイントで、ここでもTPR@FPR=0.1%は報告されていません。LPTの主指標はAccuracy/AUCです。 citeturn27view4

さらにLPTは非常に有用な失敗例も報告しています。学習中のdistortion strengthを上げると初めは性能が上がるものの、強くしすぎると**実際のtest distortionとのmismatchと、過度に破壊されたサンプルからの学習困難によって性能が下がる**としています。サイズsimulationとdistortion simulation自体の平均AUC改善も94.95→95.07→95.15と比較的小さいため、「劣化を多種類・強く入れれば入れるほど良い」という解釈はできません。 citeturn27view5

**低FPRについての一次研究の結論**としては、今回確認したDCPT、LPT、So-Fakeの主要実験のいずれにも、追加学習の効果を **TPR@FPR≤0.1%** で定量評価した結果はありません。隣接する顔anti-spoofing分野ではTPR@FPR=`10^-3`や`10^-4`を用いる先例がありますが、それはAIGI検出への性能転用を意味しません。 citeturn28search1turn28search5

したがってH1についての合理的な事前期待値は、**「平均ACCで+9〜18pt」ではなく、「低FPR改善幅は未知」**です。パイロットの検出力設計上は、まず「+10pt程度なら拾いたい」を仮の最小意味効果量にする方が安全です。

DCPT・LPTとも、2026年9月26日時点で論文本文から著者公式の実装リポジトリへの明示的なリンクは確認できませんでした。DCPT本文中のGitHubリンクは引用文献等であり、LPTについても同様です。したがって、**方法は十分再実装可能だが、checkpointからの厳密再現性はSo-Fakeほど高くない**という評価になります。 citeturn30view3turn30view4

## So-Fake-Setの構成、分離、ライセンス

So-Fake v5は2026年7月31日改訂版で、So-Fake-Setを約2Mのtraining/validation corpus、So-Fake-OODを約100Kのheld-out benchmarkと位置づけています。論文上、Set側は30のgeneration/editing models、OOD側は15のcommercial generatorsで、**両者は完全disjoint**です。実写元はSet側がCOCO、Flickr30k、OpenImages、WIDER、CelebA、OpenForensics、FFHQ、OOD側がReddit、Bluesky、Tumblr、X、Instagramです。Setではおおむねreal 650K、full synthetic 650K、tampered 650Kで、source image単位にsplitをgroup化してcontent leakageを防いでいます。 citeturn20view0

現在の公式Hugging Face dataset cardは **2,225,740 rows、総ファイルサイズ約1.28 TB** と表示しており、README metadataではtrain 1,990,070、validation 235,670です。したがって「約223万枚」という前提は現在の公開物と整合しますが、**50GB環境で全体mirrorする案は成立しません。** citeturn19search0turn19search1

生成器分離は今回かなり良好です。So-Fake-SetにはFLUX.1 dev、Kandinsky3、SD3.5、SDXL、Playground、Realistic Vision、FLUX.1-Kontext-dev、Qwen-image、Midjourneyなどが含まれます。MidjourneyやPlaygroundなどcommercial扱いの生成器もSetに含まれています。 citeturn26view0turn31view1

しかし主要ターゲットは意図的にOOD側です。Nano BananaはOOD ID 35、GPT-Image-2はID 42、Nano Banana 2はID 43です。GPT-Image-1.5もOOD ID 41にあります。したがって、**So-Fake-Setだけで学習する限り、GPT-Image-2/Nano Bananaに対する生成器leave-outは成立します。逆にSo-Fake-OODを1枚でも学習・threshold tuning・early stoppingに使うと、この利点を失います。** citeturn30view0

これはSo-Fake-R1を比較対象として使う理由にもなります。So-Fake-R1は同じbenchmark上で、OOD側に対してbalanced accuracy 72.0を報告しており、現在は論文がコード・モデル・データ公開を明記しています。したがって、CPUだけで715群を回せないという現在の制約は、**自前モデル学習を始める前にクラウドGPUを短時間借りて公開checkpointを実測する**ことで解消する価値があります。 citeturn20view0

一方、**ライセンスについては現行計画を修正すべきです。** Hugging FaceのSo-Fake-Set cardは「This work is licensed under CC BY 4.0」と明記しています。 citeturn19search0 しかし、So-Fake自身がreal sourceとして利用している上流データには別の条件があります。例えばCelebA公式は「non-commercial research purposes only」で、画像・derived dataの商用利用、および原則としてdatasetの再配布を禁止しています。 citeturn24search0 FFHQについても、個々の画像にはCC BY、CC BY-NC等が混在し、FFHQ dataset自体はCC BY-NC-SA 4.0です。 citeturn24search2turn24search4 COCOもannotationsはCC BY 4.0ですが、**画像そのものはCOCO Consortiumの所有物ではなくFlickr側の利用条件に従う**と明記しています。 citeturn24search3 Open Imagesは画像をCC BY 2.0として列挙していますが、Google自身も各画像のlicense statusを個別に保証しないと注意しています。 citeturn25search0

したがって、**「So-Fake-Set全画像バイトを一律CC BY 4.0として商用利用・再配布できる」と解釈するのは危険です。** これは法的助言ではありませんが、少なくともdataset card上の集合物ライセンスが上流画像の権利条件を自動的に上書きすると考えるべきではありません。研究パイロットであっても、将来商用運用モデルにつなげるなら、**source metadataでCelebA/FFHQ等を除外した“license-clean subset”を先に作る**か、権利確認を行う方が安全です。 citeturn20view0turn24search0turn24search2

So-Fake-OODではさらに、X/Instagram画像を再配布せずsource hyperlinkのみとし、Reddit/Bluesky/Tumblrについても適用可能なplatform policyに従い、非商用academic use等の条件を明記しています。この点でも、**OODはあくまで評価用として扱い、学習コーパスへ吸収しない**のが設計上も権利上も適切です。 citeturn21view1turn30view0

## SNS劣化再現はどこまで実環境に近いか

ここには一つ重要な訂正があります。So-Fakeの論文にある4つの「social-media propagation」は次の**評価時stress test**です。

| So-Fake条件 | 実際の処理 | So-Fake-R1 |
|---|---|---:|
| Clean | 無加工OOD | 72.0 |
| Re-enc. | 長辺1024 → JPEG Q75 | **69.5** |
| Web Dist. | 長辺1024 → WebP Q80 → JPEG Q85 | 68.2 |
| Repost | 1080×1920 canvas + padding → JPEG Q80 →評価解像度へresize | 67.0 |
| Cross-Plat. | 長辺1280 → JPEG Q85 → WebP Q80 →長辺1024 → JPEG Q75 | 65.9 |

これはあなたの運用条件である **「長辺1024 + JPEG Q75」そのものをRe-enc.条件として含んでいます。** citeturn21view0

なお、提示された「70.3/69.5」のうち、**69.5が長辺1024 + JPEG Q75**です。70.3は別のformat/resolution normalization experimentで、全画像をRGB decode → bicubic長辺1024 → **JPEG Q85**にした結果です。 citeturn26view2

また、So-Fake本文は「download、repost、screenshot、resize、platform re-encoding」を現実のsecondary propagationとして挙げていますが、**定義された4本のcontrolled propagation chainにはliteralな“スクリーンショット取得”処理は入っていません。** Repostのcanvas処理もスクリーンショットそのものではありません。したがって、Issue #68で「So-Fakeの4加工＋スクリーンショット」とするなら、スクリーンショットは**あなた独自の追加劣化**として明示すべきです。 citeturn21view0turn21view2

さらに重要なのがRRDatasetです。RRDatasetはsynthetic augmentationではなく、10,000 real + 10,000 AI-generated imagesを**Telegram、WeChat、Facebook、QQ、WhatsApp、X、Instagram、Tinderへ実際に2〜6回送信**し、単一platformだけでなくcross-platform chainも収集しています。2回10%、3回25%、4回25%、5回25%、6回15%という構成です。 citeturn21view4turn21view5

この差から、So-FakeのQ75/WebP/canvas chainは **「SNS伝送を近似する便利な合成proxy」ではあっても、「Telegram/X/Instagramの実測transfer functionそのもの」ではない**と判断すべきです。RRDatasetが示すように、実運用では圧縮だけでなく複数回のplatform固有処理が累積します。 citeturn21view6

さらにSo-Fake自身、realとfakeでnative format/resolutionが異なることをshortcut riskとして認識し、全クラスを同じ1024/Q85へ正規化するstress testを別途実施しています。これは、**学習時にfakeだけ劣化させたり、real/fakeで異なるencoding historyを持たせると、検出器が生成痕跡ではなくpipeline差を学ぶ**危険を示しています。 citeturn26view2

したがって推奨プロトコルは、合成劣化を学習に使いながら、評価は少なくとも次の二層に分けることです。

**内挿評価**では、real/fake両方へ全く同じ1024/Q75を通し、さらにSo-Fake型WebP・repost・cross-platform proxyを評価します。ここではDCPTが「既知の劣化族」に強くなるかを測ります。

**外挿評価**では、学習生成器にもaugmentation選択にも使わなかった実platform chainを用います。例えばTelegram→X、Instagram save→再JPEG、端末スクリーンショット→X等を固定し、**platform chainそのものを丸ごとholdout**します。RRDataset型の実伝送をここに置くべきです。 citeturn21view4

さらに、同じ原画像から作ったclean、JPEG、WebP、screenshot、multi-hop版は**必ず同一splitに所属させる**べきです。So-Fake自身もsource image単位でtrain/valをgroup化しています。画像variantをランダム分割すると、劣化耐性ではなくsource memorizationを測ることになります。 citeturn20view0

## 低FPR評価と必要サンプルサイズ

ここは現行計画で最も大きなボトルネックです。

FPR目標を \(p=0.001\) とし、実写評価群で**誤検知が0件**だったとします。独立なBernoulli試行を仮定した片側95%上限は

\[
p_U=1-0.05^{1/n}
\]

です。

現在の **n=586** では、

\[
p_U \approx 0.00510 = 0.510\%
\]

です。

つまり、586群で0 FPを観測しても統計的に言えるのはおおむね「FPRは95%信頼で0.51%以下」であって、**0.1%以下ではありません。** また1件誤検知しただけで経験FPRは

\[
1/586=0.1706\%
\]

となるので、そもそも0.1%という点を非パラメトリックに細かく刻むだけの解像度がありません。

0 FPを観測したときに片側95%上限を0.1%以下にするには、

\[
n\ge
\frac{\ln(0.05)}{\ln(0.999)}
\]

より **2,995独立実写群**が必要です。片側99%なら **4,603群**です。

したがって、ご提示の「FPR 0.1% の証明には実写約3,000群」という計算は**正しい**です。ただし2,995はあくまで「thresholdを固定した後に0件だった場合の最低線」です。モデル、augmentation、thresholdをその3,000群を見ながら何度も選ぶとselection biasが入るため、実務的には **calibrationとfinal confirmationを分離する方がよい**です。

このため、現コホートの586実写群を無駄と考える必要はありません。用途を変えるべきです。

現在の586群は、**screening用のFPR=1%近辺および“zero-observed-FP threshold”での比較**には使えます。FPR=1%なら期待FP数は約5.86なので、0.1%よりはずっと観測可能です。一方、このデータから「TPR@FPR=0.1%」を正式な本番指標として確定するのは避けるべきです。

生成側も現在115群では精度に限界があります。単純binomialでTPRが50〜70%付近なら、115群全体の95%区間の半幅は概ね8〜9pt、GPT Image 2/Nano Banana各57〜58群では約11〜13pt程度になります。したがって**生成器ごとの差が5pt程度ではノイズに埋まりやすい**です。

同じ生成画像に旧モデルと新モデルを走らせるpaired比較について、McNemar型の近似を使うと、80% power、両側5%、net improvement 10 percentage pointsを検出するための必要数は、両モデルの判定が食い違う割合を20〜40%と仮定して**約157〜314群**です。改善が5ptしかない場合は約628〜1,256群まで増えます。これは近似計算であり、実データのdiscordance率に依存しますが、**各主要生成器200〜300独立群**をパイロット後半の目標にする根拠になります。

学習枚数については、逆に「数千枚で十分」とする一次証拠がありません。DCPT原論文は約103K training imagesを20 epochs使用しています。 citeturn27view0 LPTはNTIREの大規模training dataに加えてSo-Fake、Chameleonを使い、8 A800で5 epochsです。 citeturn27view3 So-Fake自身のtraining-scale ablationも、10%→30%→50%→100%でOOD性能が38.3→49.4→49.9→54.2と向上しています。現在のSo-Fake-Set規模からみれば10%ですら約22万枚なので、これは**数千〜数万枚pilotの十分性を証明する結果ではありません。** citeturn27view6

さらにSo-Fakeでは、StyleGAN3だけ、LDMだけ、両者の組み合わせよりも、full multi-generator Setで大きく性能が上がり、著者はgenerator diversityをcross-domain generalizationに重要と結論しています。したがってpilotでは、**特定の数generatorから大量に取るより、30 generatorを広く薄く取る方を優先**すべきです。 citeturn27view6

私なら最初の学習pilotは **約30K画像**を起点にします。例えばSo-Fake-Set full-syntheticを30 generator × 約500 = 15K、realを約15Kとし、可能ならdeploymentに近い `kind=unknown` hard negativesを別の学習用real poolから追加します。これは「30Kで最終性能に到達する」という主張ではなく、**consistency lossに増分価値があるかを安価に判定するscreening規模**です。正の結果が出た後に50K→100K以上へscaleする方が合理的です。

評価splitは少なくとも、**generator、source-image lineage、degradation chainの三方向でleakageを止める**べきです。So-Fake-Set 30 generator内でarchitecture/family単位のleave-outをdev用途に置き、GPT-Image-2/Nano Bananaは最後まで完全未使用、あなたの最終コホートもthreshold/model選択には使わない、という構成が最もきれいです。So-Fake自体もOODをSetと完全disjointなcommercial generator群として設計しています。 citeturn20view0turn30view0

## SynthIDを先に使う戦略と、DCPTより安い代替

H5については、2026年9月時点の状況は前提時よりさらに「watermark-first」に有利です。

OpenAIは現在、対応するChatGPT、Codex、OpenAI API生成画像に **C2PA metadataとSynthID watermarkの両方**を用いると公式に説明しています。ただしcoverageはproduct、model、export path、file type、作成時期によって変わり得ます。 citeturn19search6turn23search6 OpenAI Content Provenance APIは画像についてC2PAとSynthIDを検査しますが、**対応OpenAI signalを調べるAPIであって、他社AI画像一般のdetectorではありません。** `not_detected` も「人間生成」を意味しません。 citeturn23search0turn23search4

C2PAについて、あなたの1024/Q75後に一貫して`not_detected`だったことは不思議ではありません。OpenAI自身、metadataはupload/download、file-format change、resize、screenshot等で失われたり壊れたりし得ると説明し、その弱点を補うためSynthIDを併用しています。 citeturn19search2turn19search7

一方Googleは、Gemini APIのNano Bananaシリーズについて**「All generated images include a SynthID watermark」**と明記しています。現在のAPI docsにはNano Banana、Nano Banana Pro、Nano Banana 2、Nano Banana 2 Liteが列挙され、全生成画像がSynthID対象です。 citeturn22search3 Gemini Appsについても、生成・編集したAI mediaにはSynthIDが付与されると公式Helpが説明しています。 citeturn22search0 DeepMindはSynthIDをcropping、filter、lossy compression等への耐性を意図して設計したと説明しています。 citeturn22search2

したがって、**Nano Banana系にSynthIDがそもそも付かないのではないか、という懸念はかなり低い**です。しかし、「あなたの長辺1024/Q75 + 実SNS伝送後も何%残るか」は公開資料からは分かりません。DeepMindの説明は設計目標であり、あなたのdistributionでの100% survival guaranteeではありません。 citeturn22search2

ここで、ご提示のOpenAI **31/31検出**も「観測上100%」と「母集団で100%」は区別すべきです。31連続成功から得られる片側95% exact lower boundは約**90.8%**です。100/100なら約97.0%、300/300なら約99.0%です。よってwatermarkを本番routingに使うなら、各 **model × export path × degradation path** について100〜300群程度まで増やす価値があります。

「全生成器の何割がSynthID/C2PAを付けるか」という問いには、2026年9月時点でも**信頼できる単一の割合は出せません**。母集団となる「全生成器」の定義がなく、さらにOpenAI自身がproduct/model/export/dateでcoverageが変わるとしているためです。 citeturn19search3 Google側もGeminiでのSynthID verificationは現在Google AI由来のSynthIDを識別するものと説明しており、他社がSynthIDを採用していても単一のuniversal verification endpointになっているわけではありません。 citeturn22search7

したがってglobal coverage率ではなく、あなたの流入シェアに対して、

`generator → product/version → export path → SNS path → watermark detection rate`

という**運用coverage matrix**を持つべきです。

OpenAI APIについては、公式docsで50 MiB/file、strict rate limits、Zero Data Retention対象外であることが確認できます。 citeturn23search0 一方、2026年9月26日に確認した公開Pricingページには、Content Provenance Check専用の明示的な「1 checkあたり単価」は掲載されていませんでした。したがって、production costは実際のorganization billing/API契約で確認すべきです。 citeturn23search2

この状況から、推奨アーキテクチャは **watermark OR passive detector** の二者択一ではなくcascadeです。

**第1段**でC2PA/SynthIDを照会し、信頼できるissuerのsignalが検出されたものは高信頼のprovenance-positiveとして処理します。**第2段**で`not_detected`のみを受動検知器へ送ります。そして評価レポートは「watermark込みend-to-end TPR」と「passive-only TPR」を必ず分けます。そうしないと、将来watermark coverageが変わった時に学習器本体の能力が分からなくなります。OpenAI自身もprovenance resultをbroader reviewの一要素として扱うよう推奨しています。 citeturn19search3

H6については明確で、**DCPTより先にやるべき安い実験があります。**

第一は **So-Fake-R1の直接評価**です。現在のSo-Fake v5論文はcode/model/dataset公開を明記し、R1はQwen2.5-VL-7B系を用いています。再現詳細ではLoRA rank 16/alpha 32、trainingは2×RTX 5090だったことまで公開されています。 citeturn20view0turn31view2 CPU-onlyローカル環境で715群が非現実的でも、これは「比較不能」というより**GPUを借りて一度だけ走らせるべきbenchmark**です。しかもそのモデルはGPT-Image-2/Nano Bananaを学習generatorとして使わずOOD評価しているので、今回の問いに直接近いbaselineです。 citeturn30view0

第二は **augmentation-only fine-tuning**です。全く同じbackbone、同じ画像、同じ劣化sampleを見せ、

`A: CE + degradation augmentation`

`B: clean/degraded pair + CEだけ`

`C: B + DCPT consistency`

の3条件を作るべきです。CがA/Bを低FPRで上回って初めて「DCPTに金を払う理由」があります。LPTではCE-onlyからpairwise KL/MSE追加でAUCが87.91→89.26まで上がっており、比較可能な形のablationが存在します。 citeturn27view4

第三は既存checkpointのthreshold recalibrationです。ただし、あなたの実測ではUFD/CuRe等がzero-FP pointでほぼ0検出なので、**ranking自体がhard-real tailとfakeを分離していない場合、threshold変更だけでは解決しません。** これはご提示の自前結果からの判断です。とはいえ、FPR 1%およびexpanded-real calibration setで一度ROC左端を正しく再測定してから捨てる方がよいでしょう。

## 推奨する修正版パイロットと最終判断

**計画通り進めるべき点**は、clean/degraded pair consistencyという中心アイデア、So-Fake-Setによるgenerator diversity、GPT-Image-2/Nano Bananaを学習から隔離する方針、accuracy/AUCではなくTPR@fixed-FPRを本番指標にする方針、そしてwatermarkで拾えるgeneratorのpassive-training優先度を下げる方針です。DCPTとLPTの双方がpair consistencyの有効性を異なる設定で支持し、So-Fakeはtarget generatorを明示的なOODに置いています。 citeturn30view1turn27view4turn30view0

**修正すべき点**は、最も重要な順に、FPR 0.1%評価用real setの拡大、augmentation-only control armの追加、So-Fake license-clean subset化、literal screenshotと実SNS transmission holdoutの追加、real `kind=unknown` hard-negativeを独立train/dev poolへ増やすことです。特に現在観測されているreal score tailがEXIFなしスクリーンショット・保存画像に集中しているなら、COCO中心のDCPT原論文とは負例分布が根本的に違います。**今回の成功可否はfake側のgenerator diversityだけでなく、real tailをどれだけ正しく学習・評価できるかで決まる可能性が高い**、というのが私の推測です。

**中止・置換すべき点**は、最初からNTIRE 114GBを部分downloadしてEVA-CLIP級LPTを再現すること、So-Fake全1.28TBをmirrorすること、そしてDCPTの+9.1〜17.9ptをpilotの期待TPR改善値として扱うことです。LPT本番構成は8×A800を使っており、小規模pilotの入口としては重すぎます。 citeturn27view3 まずDINOv2-B/14級で仮説を潰してからLoRAへ進むべきです。

推奨する**最小構成**は次です。

| 要素 | 推奨最小構成 | 理由 |
|---|---|---|
| Task | **REAL vs FULL_SYNTHETICの2値** | 今回の運用目標に合わせ、So-FakeのTAMPERED/localizationは第2段階へ回す |
| Backbone | DINOv2 ViT-B/14 | DCPT原論文と直接比較可能。原論文はfrozen + 197K headを4090Dで実行。 citeturn27view0 |
| 学習第1段 | frozen backbone + head | DCPT仮説を最安で検証 |
| 学習第2段 | 結果が正ならLoRA rank 8〜16 | LPT型adaptationを小規模導入。LPTはMHSA+FFN、rank 16。 citeturn26view4turn27view3 |
| So-Fake fake | 30 generator × 約500 = **約15K** | 少量でもgenerator diversity優先。So-Fakeは多generator coverageの重要性を実証。 citeturn27view6 |
| Real | 約15K + deployment hard negatives | `kind=unknown` tailを学習。ただし最終eval群とは完全分離 |
| Arms | CE-augmentation / paired CE / paired CE+consistency | augmentation効果とDCPT固有効果を分離 |
| Degradation | 1024/Q75を中心に、Q・resize・WebP/repostを**狭い範囲でjitter** | exact deploymentに重心。LPTは過度なmismatchが悪化要因と報告。 citeturn27view5 |
| Screenshot | 独自real screenshot pipelineを追加 | So-Fake 4-chainにはliteral screenshotが含まれない。 citeturn21view0 |
| External degradation test | 実Telegram/X/Instagram等の未学習chain | synthetic degradationへの過適合を検出。RRDataset型。 citeturn21view4 |
| Screening real | 現586群 | FPR 1%およびzero-observed-FP比較専用 |
| Production-FPR confirmation | **最低2,995、推奨5,000+独立real groups** | 0 FPでFPR≤0.1%を95%片側で確認 |
| Generated eval | **GPT-Image-2 ≥200〜300、Nano Banana系 ≥200〜300群** | generator別10pt級改善の判定精度を確保 |
| Watermark | 別cascadeとして常時測定 | passive-onlyとend-to-endを分離 |

50GB制約については、So-Fake-Set全体が約1.28TBなので、**streaming/選択sampling前提**にすべきです。 citeturn19search0 30K画像を選んだ後は、元画像または単一のnormalized copyだけをローカル保存し、degraded viewはon-the-fly生成すればclean/degradedを二重保存する必要がありません。平均300〜500KB/枚程度まで再符号化した30Kサンプルなら概算9〜15GBなので、model/cacheを含めても50GBに収めやすくなります。これは実際の画像サイズに依存する**推測・容量試算**です。

計算資源について、一次ソースから確実に言える基準は、DCPTが約103K画像、20 epoch、504 crop、frozen DINOv2-B/14 + 197K headを**単一RTX 4090D 24GB**で実行できたことです。ただし論文はwall-clock training timeを報告していません。 citeturn27view0 LPTは224×224、5 epochsながら大型EVA-CLIPと外部データを用い、**8×A800**です。 citeturn27view3

したがって以下は論文実測値ではなく、pilot planning用の**推測**です。

| GPU | 30K paired / DINOv2-B frozen-head | 30K paired / DINOv2-B LoRA | 評価 |
|---|---:|---:|---|
| RTX 4090 24GB | 約1〜3時間 | 約4〜10時間 | pilot最有力 |
| L40S 48GB | 約1〜2時間 | 約3〜7時間 | batchを大きくしやすい |
| A100 80GB | 約1〜2時間 | 約3〜7時間 | 安定だがpilotにはやや高価 |
| H100 80GB | 1時間前後〜 | 約2〜5時間 | 速度優先時のみ |

504px入力、重いonline JPEG/WebP decode、大量worker不足、pairを別forwardする実装ではこの範囲を超え得ます。したがって最初に1K〜2K sampleでthroughput benchmarkを取ってからfull pilotへ外挿するのが妥当です。**EVA-CLIP Big-E級のLPT再現時間をこの表から推定してはいけません**。LPTは別クラスの計算量です。 citeturn27view3

最終的な優先度は次の通りです。

| 優先度 | パイロット開始前／初期に行うこと | Go/No-Goへの意味 |
|---:|---|---|
| **P0** | **So-Fake-R1公開modelをレンタルGPUで現在の715群に実行** | 自前学習を始める前の最重要baseline。公開報告ではtarget generatorがOOD条件。 citeturn20view0turn30view0 |
| **P0** | **実写評価群を最低2,995、可能なら5,000+独立groupへ拡張** | これをしない限り「FPR≤0.1%達成」は証明できない |
| **P0** | **Nano Banana / Nano Banana 2のSynthIDを同じ1024/Q75 + SNS chainで100〜300群測る** | Google公式では全生成画像にSynthID。実環境survivalを確定。 citeturn22search3turn22search4 |
| **P0** | So-Fake上流licenseを監査し、CelebA/FFHQ等を除いた利用可能subsetを確定 | 将来の商用化・再配布リスクを学習前に除く。 citeturn24search0turn24search2 |
| **P1** | 30K程度で **CE augmentation / paired CE / DCPT** の3-armを同条件実験 | DCPT固有の上積みを直接測る |
| **P1** | `kind=photo` / `kind=unknown`を必ず別々にFPR報告 | 現在のreal-tail問題を平均値で隠さない |
| **P1** | exact 1024/Q75と、未学習の実SNS multi-hopを別々に評価 | 内挿耐性と真のdeployment外挿を分離。 citeturn21view0turn21view4 |
| **P1** | GPT-Image-2/Nano Bananaを各200〜300群以上へ増強 | 10pt級のgenerator別改善を判定可能にする |
| **P2** | DCPTがaugmentation-onlyを明瞭に上回った場合だけDINOv2/CLIP LoRAへ拡張 | 不要なLoRA学習を回避 |
| **P2** | 50K→100K+へscaleし、generator diversityを維持 | So-Fakeのscale/diversity結果に沿う。 citeturn27view6 |
| **P3** | それでも不足する場合のみNTIRE dataset/LPT大型backboneを導入 | ストレージ・GPUコストの大きい手段を最後に回す |

**パイロット継続条件**は、「So-Fake-R1に勝つこと」だけに固定するより、DCPTのincremental valueを直接見る方がよいです。具体的には、まず現586群でTPR@FPR≈1%とzero-observed-FP pointをscreeningし、**DCPT armが同一劣化を見たaugmentation-only / paired-CE armに対し、GPT-Image-2・Nano Banana双方で一貫した改善を示すこと**を要求します。そのうえで拡張real confirm setにthresholdを固定し、0 FP / ≥2,995群を満たした状態で生成TPRを比較します。

逆に、**DCPTがaverage accuracy/AUCだけ改善し、`kind=unknown`の実写上側tailが動かない、または一緒に上がってTPR@0.1%が改善しない場合は、その時点でDCPT scale-upを中止**すべきです。これは十分あり得る失敗モードです。DCPT自体が低FPR tailを直接最適化しておらず、原論文でもACC改善に比べAUC改善が小さいためです。 citeturn30view1 その場合は、より大きなbackboneへ進む前に、deployment hard-negative miningやFPR-tailを直接意識した学習目的へ設計を切り替える方が合理的です。

したがってIssue #68の最終評価は、**「DCPT + So-Fakeという方向は妥当。ただし、“+9〜18ptが本コホートの0.1% FPR点でも再現する”という期待は捨てる。まずSo-Fake-R1実測、watermark coverage確定、real評価母数拡張、augmentation-only controlを済ませ、その後30K級DINOv2 pilotを回す」**です。この順序なら、1.28TBのdataset mirrorや8×A800級の再現に進む前に、最も不確実な仮説――**「スクリーンショット実写の極端な裾を壊さず、最新generatorのscoreだけを上げられるか」**――を最小コストで検証できます。