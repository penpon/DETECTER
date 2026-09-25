# SNS投稿画像のAI検出が壊滅する原因と、VLM／マルチモーダルOSSによる代替フロー — 2026年9月時点

## 仮説判定と要旨

ご提示の実測――**実写側にも生成側にも同じ「長辺1024px＋JPEG品質75」処理を施し、実写側で誤検知ゼロになる閾値を採用すると、3検出器ORの生成検出が38/91→1/91まで崩壊した**――は、2025–2026年の「実世界伝送・SNS再投稿」を意識した研究結果と方向としてかなり整合しています。ただし、最も重要な修正点は、**「高周波が消えるから全検出器が死ぬ」ではなく、「cleanデータ上の局所的・生成器固有shortcutに依存した検出器が、JPEG・resize・スクリーンショット等でクラス間分離を失う」**と捉えることです。GlobalForgeはまさにこの現象を局所artifact依存として分析しており、resizeだけでも前処理不一致により約8.8ポイントのBAcc低下を観測しています。citeturn19view1

| 仮説 | 判定 | 2026-09時点の結論 |
|---|---|---|
| **H1. 周波数・artifact系はSNS加工で構造的に死ぬ** | **一部成立** | 従来型の局所・周波数・pixel fingerprint依存モデルはJPEG、resize、実SNS伝送で極端に崩れる例が多数ある。一方、phase-spectrum、degradation-consistency、global-structure、巨大foundation backbone＋augmentationで耐性を獲得する研究も出ており、「周波数系は原理的に全滅」は強すぎる。citeturn19view1turn18academia28turn18search0 |
| **H2. 意味・コンテンツ系はSNS耐性がある** | **一部成立** | semantic/global/physical cueはJPEGで直接消えにくく、pixel-onlyより安定する傾向は明確。ただしgeneric VLMも実SNS転送で低下し、最新生成器は意味破綻自体が少ない。citeturn16view0turn22academia16 |
| **H3. VLM単体が既存検出器を上回る** | **不成立** | GPT-4o級がclean条件で多数の専用検出器を上回る例はあるが、実伝送では低下する。Qwen系generic VLMはさらに弱い。「画像を渡してAIか尋ねる」だけでは強い専用検出器を一貫して超えない。citeturn22academia16turn16view4 |
| **H4. 検出専用OSS VLMが存在する** | **成立** | So-Fake-R1、FakeVLMなどはコード／モデルが公開され、FakeVLM-R1、AlignGemini等も検出専用reasoningを研究している。So-Fake-R1は特にSNS OODを目的化している。citeturn22search2turn14search3turn15view1 |
| **H5. semantic＋low-level＋provenanceのハイブリッドが必須** | **一部成立** | 2026年の強い結果はハイブリッド化を支持する。So-Fake-R1ではsemantic-only／forensic-onlyより統合系が明確に上回る。ただし**FPR≤0.1%かつTPR≥90%**をSNS加工後で実証した公開研究は確認できない。citeturn22search4turn15view1 |
| **H6. SNS耐性ベンチマークが存在する** | **成立** | RRDataset、So-Fake、NTIRE 2026、RealDeg-Benchは明示的に伝送・JPEG・resize・複合劣化を扱う。特にSo-Fakeは**1024px＋JPEG75**というご提示条件とほぼ同一の再エンコード条件を含む。citeturn22search4turn22search1turn19view1 |

なお、名称上の一点だけ補足すると、**UniversalFakeDetect / UnivFD（Ojha et al.）の原論文はCVPR 2023**です。CVPR 2024のCLIP系としてはCozzolinoらの *Raising the Bar of AI-generated Image Detection with CLIP* などが別にあります。citeturn15view1turn19view1

**総合結論は、現在の実運用では「既存binary forensic detectorを別のgeneric VLMに置き換える」のではなく、`provenance → degradation-robust visual detector → task-tuned semantic/reasoning VLM → calibrated fusion/abstain` に組み替えるべき、というものです。** So-Fake-R1とAlignGeminiは、この分業思想をかなり直接的に実装しています。citeturn22search2turn15view1


## 従来検出器がSNS加工で死ぬ機序と、意味信号が比較的残る理由

### 問題は単なる「高周波消失」より広い

従来のAIGC画像検出器が拾ってきた代表的signalには、生成器のupsampling周期性、局所pixel correlation、スペクトル異常、noise residual、diffusion reconstruction errorなどがあります。GlobalForgeは2026年、既存検出器の劣化を**小さな空間近傍に残るgenerator-specific local artifactsへのshortcut学習**として整理し、JPEG quantization・resize resampling・blurがその局所スペクトルを直接変形すると論じています。citeturn19view1

JPEGではブロックDCT後の量子化によって、とくに小振幅・高周波係数が粗く量子化されます。一方、resizeでは補間により隣接pixelが再合成され、局所相関・aliasing・grid patternが変わります。GlobalForgeの制御実験では、center-cropで学習したUnivFDをresize入力に変えただけで約8.8ポイントBAccが落ち、著者らは「意味内容と大域配置はほぼ保存されているのだから、失われたsignalは局所pixel側である」と解釈しています。citeturn19view1

したがって、ご提示の

> 生画像ではCommunity Forensics / CuReに高スコア生成画像が存在したが、1024＋JPEG75後に消える

という現象は非常に自然です。それ以上に重要なのが、

> スクリーンショット等を含む実写側の最大スコアまで上がる

点です。低レベル検出では「fake signalが小さくなる」だけではなく、**real側にも再符号化、resampling、screen capture、sharpening、色変換等に由来する異常統計が入り、score distributionの右裾が広がる**ためです。So-Fakeは全クラスを同じresolution/formatへ正規化するとUnivFDが48.6→44.1、EFFORTが65.5→62.2、Qwen2.5-VL-7Bが65.3→61.8となる一方、So-Fake-R1は72.0→70.3に留まると報告しており、ファイル形式・解像度のshortcutを消すだけでも検出器間の差が現れます。citeturn12view1

これは**低FPR運用では決定的**です。通常の論文がaccuracy/BAcc/AUCの平均性能を見るのに対し、ご提示の運用は実写scoreの最大付近を閾値にするため、平均分離ではなく**real distributionの極端な右裾**がTPRを決めます。したがって、論文でAUC 0.95–0.98のモデルが「実写586件でFPゼロになる閾値」ではほぼ何も拾わない、という結果は矛盾しません。NTIRE 2026のトップは変換込みでROC-AUC約0.972でしたが、この数字だけからFPR=0.1%地点のTPRは一切導けません。citeturn22search1turn4view0

### 実SNS伝送では実際にどれほど落ちるか

RRDatasetは2025年、10,000 real＋10,000 fakeをTelegram、WeChat、Facebook、QQ、WhatsApp、X、Instagram、Tinder等で複数回転送し、さらに印刷→撮影、画面撮影、投影撮影などまで試しています。17種類の専用detectorと10種類のVLMを同一条件で比較した、H1/H2/H3に非常に直接的な資料です。citeturn6view0turn22academia16

代表値を見ると、internet transmission後の**fake-class accuracy**は、Freq-Netが4.47%、Fusingが7.38%、SAFEが0.88%まで崩れました。一方、DRCTは92.82%、DIREは90.34%、DNFは90.98%と伝送には比較的耐えましたが、re-digitizationではDIREが1.42%、DNFが0.05%まで崩壊しています。DRCTはre-digitizationでも64.34%を残し、全条件overall 89.59%で同評価中トップでした。つまり**「artifact検出器なら全部同じように死ぬ」のではなく、学習signalとdegradation exposureによって耐性差が極端に大きい**のが実態です。citeturn6view0

2026年のGlobalForgeはこの観察をさらに押し進め、局所signalを意図的に抑えるLocal Information Bottleneckと、遠距離tokenだけから証拠を集めさせるGlobal Structural Reasoning、clean/degraded featureを揃えるcontrastive lossを組み合わせ、RealDeg-Benchで平均BAcc 85.81%、in-the-wild 8群で85.93%を報告しました。同一backboneのplain baselineはそれぞれ80.03%、80.21%でした。コード、pretrained weights、RealDeg-Benchも公開するとしています。citeturn19view1

さらにDCPT（Degradation-Consistent Paired Training）は、clean viewとdegraded viewのfeature/outputを明示的に揃えるだけで、Synthbusterの8劣化条件平均を同一baseline比+9.1ポイント、JPEG条件では+15.7～17.9ポイント改善したと報告しています。追加parameter・推論overheadを必要としない点も実用的です。citeturn18academia28

したがってH1の最終形は、

> **「clean-trainedな局所／生成器fingerprint依存はSNS加工に構造的に弱い。ただしdegradation invariantなsignalを明示的に学習させれば回復可能」**

です。CVPR 2026にはタイトル通り圧縮画像をphase spectrumのrobustnessから検出する研究も登場しており、「frequency domainそのものが使えなくなった」という結論にもなりません。citeturn18search0

### VLMが比較的残すsignal

VLMの利点はJPEG artifactを魔法のように見破ることではなく、**量子化で消えにくい高次の関係**を判断材料にできる点です。例えば、不自然な文字列、指や身体構造、物体の接続、幾何、影、鏡・反射、因果的に不自然な配置、全景にまたがる構造整合性などです。AlignGeminiはこれを明示的に「semantic consistency」と「pixel-artifact detection」に分解し、Qwen2.5-VL系VLMをsemantic側、DINOv2系expertをpixel側に割り当てます。著者らの実験では、VLMをpixel artifact supervisionに寄せるとtransferが悪く、semantic supervisionに使う方がgeneralizationが良いと報告されています。citeturn15view1

ただし**semantic signalは“圧縮されても残る”だけで、“必ず存在する”わけではありません。** So-Fakeは最新の商用生成器をtrainingと完全disjointにして評価しており、専用semantic/forensic hybridでもOOD detectionが72.0程度に留まります。最新生成器で明白な手指・文字・構図破綻が減るほどsemantic-only検出の天井も下がる、というのが妥当な推論です。citeturn22search4

**推測:** GPT Image 2／Nano Banana級を対象にすると、2022–2024年頃によく使われた「指がおかしい」「文字が壊れている」を主signalにするrule-based/VLM promptは主検出器ではなく補助signalに格下げすべきです。むしろ、**大域的整合性＋物理的反証＋低レベルexpertとの不一致**を利用する方が今後の方向性と整合します。FakeVLM-R1やAlignGeminiがこの方向へ移っていることが、その傍証です。citeturn17view3turn15view1


## SNS耐性ベンチマークと定量結果

実運用に最も重要なのは、2026年時点で「clean benchmark accuracy」より**同一のSNS変換をreal/fake双方に施した評価**が出始めたことです。

| ベンチマーク／研究 | SNS・劣化条件 | 重要な結果 | コード等 |
|---|---|---|---|
| **So-Fake / So-Fake-OOD, 2026** | 実SNS real画像5 platform＋trainingとdisjointな商用generator。Propagation試験に**長辺1024＋JPEG Q75**を明記 | So-Fake-R1 **72.0→69.5**、EFFORT **65.5→60.1**、UnivFD **48.6→45.5**。さらに複合cross-platform処理ではSo-Fake-R1 65.9。citeturn9view0turn9view2 | dataset、inference code、model weights公開。citeturn22search2 |
| **RRDataset, ICCV 2025** | SNS 8種で2–6回転送＋scan/print/screen/project re-digitization | SAFE/Freq-Net/Fusingなどがtransferで壊滅。一方DRCTはinternet transmission fake 92.82%、re-digitization 64.34%。citeturn6view0 | benchmark中心 |
| **NTIRE 2026 Robust AIGI Detection** | real/fake**双方**に1–5連続の変換。36変換、42 generator、cropping/resizing/compression/blur等 | top robust ROC-AUC **0.9723 / 0.9721**。大規模DINOv3＋強いaugmentationが上位。citeturn22search1turn4view0turn4view1 | challenge benchmark |
| **RealDeg-Bench / GlobalForge, 2026** | 7 degradation＋multi-step compound chain | GlobalForge平均BAcc **85.81%**、plain同一backbone 80.03%。citeturn19view1 | code、weights、benchmark公開。citeturn19view1 |
| **FakeVLM-R1, 2026** | JPEG70/80、resize 0.5/0.75、noise、blur等 | JPEG70でoverall accuracy変化 **−10.29pt**、JPEG80 **−6.57pt**、resize×0.5 **−8.41pt**。旧FakeVLMはJPEG70で−20.07pt。citeturn16view5turn17view3 | 論文あり。今回確認範囲ではR1の公開weight状態はSo-Fakeほど明確でない |
| **AlignGemini, 2025/26** | JPEG、double JPEG、resize、double resize | semanticを含むモデルはpixel-onlyより安定し、AlignGeminiが同比較で最もrobustと報告。citeturn16view0turn16view1 | 論文あり。今回確認した一次ソースでは公開artifact状況を確証できず |

ここで**So-Fakeの「Re-enc」条件が特に重要**です。論文のpipelineは長辺1024にresizeした後JPEG quality 75で再符号化しており、ご提示のSNS模擬処理とほぼ同一です。さらに同論文はWebP/JPEGを連鎖させるWeb Distribution、1080×1920 canvasを挟むRepost、1280→JPEG85→WebP80→1024→JPEG75というCross-Platform chainまで評価しています。citeturn9view0turn12view0

ただし、So-Fakeの69.5%とご提示の「1/91」を直接比較してはいけません。**評価指標と閾値が全く違うからです。** So-Fake等はaccuracy/BAccに近い通常動作点、ご提示値は「実写側誤検知ゼロ」に閾値を押し上げた低FPR動作点です。実運用で重要なのは後者なので、今後の社内benchmarkの主指標はaccuracy/AUCではなく、**TPR@FPR=1%、0.1%、可能なら0.01%**にすべきです。

### generic VLMは本当に強いのか

RRDatasetではzero-shot GPT-4oが元画像でfake 96.30%、real 92.68%と非常に強く、clean条件では17専用detector中16種を上回る水準でした。しかしinternet transmission後はfake 79.41%、real 90.01%、re-digitization後はfake 69.23%、real 76.92%まで低下し、全条件overallは84.09%。専用DRCTの89.59%には届きませんでした。Qwen2.5-VL-72Bはさらに弱く、internet transmissionでfake 22.87%、real 89.95%でした。citeturn6view0

FakeVLMの評価でも、generic GPT-4oはFakeClue detection 47.4%、Qwen2-VL-72B 57.8%、InternVL2-40B 50.7%なのに対し、検出専用fine-tuneされたFakeVLMは98.6%でした。これは同モデルのtraining domainに有利な評価でもあるため数値をそのまま一般化すべきではありませんが、少なくとも**「大きなVLMに“AI生成ですか？”と聞けばよい」という仮説を否定する強い証拠**です。citeturn16view4

FakeVLM-R1のablationはさらに明快です。unaligned base modelはreal 96.2%に対しfake 26.6%、overall 61.4%しかなく、SFT＋GRPO＋critical-thinkingを組み込むとreal 95.9%、fake 95.2%、overall 95.5%になりました。つまり**VLMのサイズそのものより、検出taskへのalignmentが重要**です。citeturn17view3

したがってH3への回答は明確で、

> **商用VLM／Qwen／InternVL／LLaVAをzero-shot/few-shotで直接聞く方式を、UFD等の“modern replacement”とするのは推奨しない。検出専用にfine-tune／RL／expert fusionされたVLMなら別物として有望。**

です。


## VLM・意味系OSSの実用性とモダンな候補

### So-Fake-R1が現時点で最も要件に近い

今回の条件に最も直接刺さるのは**So-Fake-R1**です。So-Fake-OODは約100Kのheld-out benchmarkで、real側をReddit、X、Instagram、Bluesky、Tumblrから取得し、fake側はtraining generatorと分離した商用generatorを使います。So-Fake-Setは約200万画像・12カテゴリ、real / full synthetic / tamperedの3 scopeを扱います。公式repositoryではinference code、weight download script、datasetを公開しています。citeturn22search2turn22search4

構造は単一VLMではありません。**Visual Observer**が意味的な手掛かりを作り、**Forensic Evidence Provider**が低レベル異常を作り、evidence gateが十分なケースを処理、曖昧・矛盾ケースのみ**Decision Maker**に渡します。これはユーザー仮説H5の「semantic＋forensics」をほぼそのまま実装したものです。citeturn22search2

さらにablationが重要で、semantic Observer onlyのOODが64.4、forensic Provider onlyが59.3、単純voteが67.5なのに対し、完全版So-Fake-R1が72.0でした。つまり、**ORを取るだけではなく、証拠の信頼性と矛盾を処理するarbitrationが効いている**ことになります。citeturn9view3

これはご提示の「3者OR」との大きな違いです。低FPRではORは各detectorのfalse-positive tailを足し合わせる方向に働くため、独立branchを増やすほど閾値校正は難しくなります。So-Fake式の**selective gating / learned fusion**の方が低FPR用途に理にかなっています。

### FakeVLMとFakeVLM-R1

FakeVLMはNeurIPS 2025系の検出専用multimodal modelで、100K超のFakeClueを使い、binary verdictだけでなくartifactを自然言語で説明します。公式GitHubも公開されています。citeturn14search3turn15view2

ただし、2026年のFakeVLM-R1論文は旧FakeVLMの弱点をかなり率直に示しており、JPEG70でoverall −20.07pt、blur条件ではreal accuracyが−94.70ptという極端なケースまで報告しています。つまり**「VLMだからpixel shortcutを使わない」という理解は誤り**です。VLMもSFTの仕方次第で表層artifactにoverfitします。citeturn17view3

FakeVLM-R1はこれに対し、「fakeである根拠」だけでなく**authenticity counter-proof**を同時に作らせ、物理常識に照らして両側から検証するcritical-thinking＋GRPO方式を採ります。JPEG70のoverall低下を−10.29ptまで半減し、全perturbation平均変動を旧FakeVLMの9.44%から3.63%へ縮小したと報告しています。citeturn16view5turn17view3

この「realである根拠も積極的に探す」発想は、**スクリーンショットrealをAIと誤認する問題**に特に相性が良い可能性があります。ただし、これは現時点ではユーザー分布で未検証なので**推測**です。

### AlignGeminiとCO-SPY型の分業

AlignGeminiはVLMを万能化するのではなく、

`VLM → semantic consistency`

`DINO系expert → pixel forensics`

とtaskを分けます。論文では5つのin-the-wild benchmark平均で既存系に対し+9.5ポイントとし、JPEG・double JPEG・resize・double resizeでも高い安定性を報告しています。citeturn15view1turn16view0

同論文はCO-SPYのようなsemantic featureを含む既存法がpixel-onlyのNPR等よりpost-processingに安定するとしています。したがって**CO-SPYは「従来forensicとVLMの中間」候補として再評価価値がある**ものの、今回確認した資料だけでは「1024＋JPEG75・FPR 0.1%」を直接証明できません。citeturn16view0turn16view2

### EFFORT、SAFE、FatFormerの位置づけ

**EFFORT**はICML 2025系のgeneralizable AIGI detectorで、VLM生成回答型ではなくvision foundation representationを効率よく適応するタイプです。So-Fake-OODでは65.5、長辺1024＋JPEG75で60.1でした。UnivFDの48.6→45.5より良く、**軽量なvisual branch候補**として現実的です。公式実装も公開されています。citeturn9view2turn13search10

一方、SAFEはRRDatasetのinternet transmissionにおけるfake detectionが0.88%まで低下しており、少なくともその設定では「SNS robust detector」と呼ぶのは困難です。FatFormerもSo-Fake-OODで59.8程度で、2026年の最新social OODに対する第一候補とは言いにくい状況です。citeturn6view0turn10view2

**AIGCDetectBenchmark**は主としてbenchmark名として扱うべきで、「AIGCDetect」という一つのmodern VLM detectorがある、と混同しない方が安全です。AlignGeminiはGenImage、DRCT-2Mと並んでAIGCDetectBenchmarkを自己合成系のgeneralization評価に用いていますが、これはSo-FakeやRRDatasetほど直接的なSNS transmission benchmarkではありません。citeturn16view1

### 「Jevのような枠組み」について

ご指定の**Jev**については、今回2026年9月24日時点の公開一次ソースを検索した範囲で、AI生成画像真贋判定用OSSとして一意に同定できませんでした。そのため固有製品／repositoryとしての性能評価は**証拠不足**とします。

ただし、仮にJevが「任意のQwen/InternVL/LLaVA等へ画像を渡し、説明とverdictを生成するorchestration layer」を指しているのであれば、**そのままでは検出器とは見なさない方がよい**です。RRDataset、FakeVLM、FakeVLM-R1の結果はいずれも、generic visual QAより**検出専用supervision・reasoning・expert evidence**が必要であることを示しています。citeturn6view0turn17view3


## 来歴・生成器識別とハイブリッド設計

### C2PAは強いが「無い＝実写」ではない

SNS運用ではprovenanceを最初に見るべきですが、それを唯一の判定手段にしてはいけません。C2PA自身のimplementation guidanceは、social media等の非対応platformでmanifestを含むmetadataが削除・破損し得ることを明記しています。現行C2PA 2.4には、metadataが消えた場合にperceptual fingerprintやinvisible watermarkの**soft binding**を用いて外部manifest repositoryからcredentialを復元する仕組みがあります。citeturn24search0turn24search2turn24search5

したがって構造は、

**C2PAあり・署名検証成功 → 強いpositive provenance evidence**

**C2PAなし → unknown**

であって、

**C2PAなし → real**

ではありません。これはご提示条件のようにmetadataが最初から剥落している場合、とくに重要です。citeturn24search9

OpenAI自身も2026年5月、C2PA metadataはupload/download、format conversion、resize、screenshotで失われ得るため、画像ではC2PAに加えてinvisible watermarkを使う多層provenanceへ移行していると説明しています。2026年9月公開のChatGPT Images 2.5についてもC2PA metadataとinvisible watermarkを継続するとしています。citeturn24search1turn24search8

さらに2026年のOpenAI public verification toolは、OpenAI由来のSynthID watermark検出とC2PA表示を行うと説明されています。これは**OpenAI生成であることのpositive attribution**には、画像内容から推測するclassifierより本質的に強い経路です。citeturn24search18

### GPT Image 2／Nano Banana級の「生成器識別」はさらに難しい

binaryの`real vs AI`と、`OpenAI vs Google vs Midjourney vs Flux...`のattributionは別問題です。

GlobalForgeの解析が示すように、従来のgenerator attributionに使いやすいsignalはまさにgenerator-specific local fingerprintsであり、JPEG・resizeで壊れやすいsignalです。したがって、**metadataなし・Q75＋1024後にモデルfamilyまでvisual-onlyで当てる課題は、binary detection以上に脆いはず**というのが自然な推論です。citeturn19view1

今回調べた一次文献の範囲では、**GPT Image 2級とNano Banana級を含み、1024＋JPEG75後にも高精度なgenerator-family attributionを行い、しかもFPR 0.1%級で検証した独立OSS**は確認できませんでした。これは**証拠不足**です。

So-Fakeが2026世代の商用generatorまでOODに含めながら、まずreal/full-synthetic/tamperedの真贋scopeを問題にしているのも示唆的です。最新social-media benchmarkでも、モデルfamily attributionよりbinary/scope detection自体がまだ解決していません。citeturn22search4

したがって現在の優先順位は、

**vendor watermark / soft bindingによる直接attribution > visual fingerprint attribution**

です。

### 推奨する実運用フロー

2026年時点で最も妥当なのは、次のような**非対称ハイブリッド**です。

**来歴層**ではC2PA、soft binding、vendor invisible watermarkを検査します。署名付きpositive provenanceが得られた場合だけ強く採用し、何も見つからなければunknownとして次段へ流します。C2PA 2.4はmanifest stripping後のsoft-binding recoveryを明示しています。citeturn24search0turn24search2

**visual forensic層**には、UFDを主軸に残すよりGlobalForge、EFFORT、あるいはDCPT的に**ご自身のexact SNS degradationでpaired trainingしたDINO/CLIP系expert**を置く方が合理的です。GlobalForgeとDCPTはいずれも「degradationをaugmentationとして偶然学習する」のではなく、feature invarianceを直接学ばせる方向です。citeturn19view1turn18academia28

**semantic/reasoning層**にはgeneric Qwenへの単発質問ではなく、So-Fake-R1、FakeVLM-R1型のtask-aligned VLMを置きます。判定だけでなく、「偽を支持する観察」「真を支持する反証」「両者の確信度」を構造化出力させる方がfalse-positive suppressionに向きます。citeturn22search2turn17view3

最後に**fusion層**を置きます。ここは単純ORではなく、branch score、processing type、image category、provenance evidenceを入力するcalibrated meta-classifierまたはgating modelにし、さらに`AI-confirmed / suspicious / inconclusive / likely-real`のようなabstentionを許すべきです。So-Fake-R1で単純vote 67.5に対しfull arbitration 72.0だった結果は、この設計を直接支持します。citeturn9view3

概念的には、

```text
Input image
   │
   ├─ Provenance
   │    ├─ valid C2PA / watermark hit → strong AI/source evidence
   │    └─ none → UNKNOWN（realとはしない）
   │
   ├─ Robust visual forensic expert
   │    └─ GlobalForge / EFFORT / degradation-consistent model
   │
   ├─ Semantic / reasoning VLM
   │    └─ So-Fake-R1 / FakeVLM-R1-style reasoning
   │
   └─ Calibrated fusion
        ├─ high-confidence AI
        ├─ likely AI → human/review queue
        ├─ inconclusive
        └─ likely real
```

が妥当です。

**H5の「FPR≤0.1% & TPR≥90%」については、2026年9月時点でこの条件をSNS加工済み・最新商用generator OODで実証した設計は確認できません。** NTIREのAUC≈0.97、GlobalForgeのBAcc≈86、So-Fake-R1のQ75 accuracy≈69.5はいずれも、その低FPR operating pointの達成を意味しません。citeturn4view0turn19view1turn9view2


## 低FPR運用の統計設計と、ご提示実測の意味

ここは検出器選定以上に重要です。

### 実写586群ではFPR 0.1%を証明できない

独立な実写群を \(n\) 件評価してfalse positiveが0件だったとき、binomial proportionに対する**片側95% Clopper–Pearson上限**は

\[
p_{\mathrm{upper}}
=
1-0.05^{1/n}
\]

です。

ご提示の**586 real groupsでFP=0**なら、

\[
p_{\mathrm{upper}}
=
1-0.05^{1/586}
\approx 0.005099
\]

なので、

**FPR < 0.510%（片側95%）**

までしか証明できません。

FPR ≤0.1%を0 FPで片側95%証明するには、

\[
1-0.05^{1/n}\le0.001
\]

を満たす必要があり、

\[
\boxed{n\ge 2995}
\]

です。

つまり**最低2,995独立real groupsでFPゼロ**が必要です。

許容FP数ごとの必要real group数は次の通りです。

| 観測FP | FPR≤0.1%を片側95%で主張する最低n | 観測率 |
|---:|---:|---:|
| 0 | **2,995** | 0 |
| 1 | **4,742** | 0.0211% |
| 2 | **6,294** | 0.0318% |
| 3 | **7,752** | 0.0387% |
| 5 | **10,511** | 0.0476% |

したがって現在の「誤検知0点」というthreshold選択はengineering上は有用でも、統計的には**「真のFPRが0.1%以下」とはまだ言えません**。

さらに重要なのは、画像variantを増やしても独立sample数が増えないことです。同一原画像のJPEG75、JPEG85、resize、screenshotを4枚作って4件と数えるのではなく、**原画像／投稿単位の独立group**で数えるべきです。そうしないとconfidence intervalを過度に狭く見積もります。

### TPR≥90%の証明条件

同様に片側95%でTPR>90%を証明する場合、全件成功なら最低29 fake groupsが必要です。

しかし全件成功を期待するのは現実的ではありません。現在と同じ**115 fake groups**なら、最低でも

\[
110/115 = 95.65\%
\]

を検出しないと、片側95% lower boundが90%を上回りません。109/115 = 94.78%ではlower boundが約89.96%で、わずかに届きません。

つまり「点推定で90%」では全く不十分で、目標が

> **真のTPR ≥90%を95% confidenceで保証する**

なら、observed TPRは95%前後以上必要になります。

### ご提示の1/91は論文benchmarkより悪いのではなく、別の問題を測っている

3者ORがSNS処理後1/91という結果は約1.1% TPRですが、そのthresholdはreal側でFPを出さないように強く制約されています。

一方、論文で「UnivFD Q75後45.5%」「GlobalForge BAcc 85.8%」「NTIRE AUC 0.97」と報告されていても、これは同じ動作点ではありません。citeturn9view2turn19view1turn22search1

むしろ、ご提示の結果から優先的に疑うべきなのは、

1. fake scoreがJPEG/resizeで下方移動したこと、
2. screenshotを含むreal scoreの右裾が上方移動したこと、
3. その結果**low-FPR thresholdで両分布のtail separationが消滅したこと**

です。

今後はaccuracyより、各モデルについて

\[
\mathrm{TPR}@\mathrm{FPR}
=
10^{-2},10^{-3},10^{-4}
\]

のpartial ROCを描く方が遥かに有益です。

特にreal側は最低3,000群、できれば5,000–10,000群まで増やし、iPhone/Android、camera original、screenshot、messaging再保存、X/Instagram相当、multiple repost等を**deployment prevalenceに合わせて層化**するのが望ましいです。

**推測としての現実的目標設定:** visual-only detectorだけで「最新商用generator OOD＋SNS Q75/1024＋FPR 0.1%でTPR 90%」をproduction acceptance条件にすると、2026年公開結果からは達成根拠がありません。まずは**FPR 0.1%を統計的に証明した状態で、TPRをどこまで引き上げられるか測定する**のが妥当です。90%は現時点ではengineering baselineではなく研究目標として扱い、provenance hitを別channelとして加算する設計が現実的です。citeturn22search4turn19view1


## 優先度順アクションと導入候補

最も重要なのは「VLMへ全部置換」ではありません。**ご提示のexact distributionを保ったまま、壊れにくいvisual branchと検出専用VLM branchを追加し、low-FPRで再校正する**ことです。

| 優先度 | 候補／施策 | 導入可否 | SNS耐性の証拠・期待値 | 実装コスト | 判断 |
|---|---|---|---|---|---|
| **最優先** | **So-Fake-R1** | **可。公式inference code＋model weight公開**。citeturn22search2 | exact **1024＋JPEG75: 72.0→69.5**。semantic＋forensic＋arbitration。citeturn9view2turn9view3 | 中～高、7B級VLMを含む | **最初に入れるべきVLM系** |
| **最優先** | **GlobalForge** | **可。code＋pretrained weights＋RealDeg-Bench公開**。citeturn19view1 | RealDeg平均BAcc **85.81**、compound degradation対応。局所artifact依存を抑制。citeturn19view1 | 中 | **visual forensic branch第一候補** |
| **最優先** | **C2PA 2.4＋soft binding＋vendor watermark検査** | 可 | metadata strippingに対しsoft binding recoveryを規格化。OpenAIはC2PA＋invisible watermarkを併用。citeturn24search0turn24search1 | 低～中 | **positive provenanceを最上流に置く** |
| **高** | **EFFORT** | **可。公式OSSあり** | So-Fake OOD 65.5、1024/Q75 60.1。citeturn9view2turn13search10 | 低～中 | 軽量比較baseline／ensemble expert向け |
| **高** | **自前DCPT型再学習** | 実装可 | degraded平均+9.1pt、JPEG +15.7～17.9pt報告。citeturn18academia28 | 中 | **自社分布に一番合わせやすい** |
| **高** | **FakeVLM-R1型reasoning** | 論文再現候補。公開weight状況は今回確証不足 | JPEG70 −10.29pt、旧FakeVLMの−20.07ptより大幅改善。citeturn17view3 | 高 | So-Fake-R1の次の研究候補 |
| **中** | **AlignGemini型 semantic＋pixel expert** | 論文実装可。今回一次ソースでrelease状況確証不足 | 5 in-the-wild平均+9.5pt、JPEG/resize robust。citeturn15view1turn16view0 | 中～高 | **設計思想として非常に有力** |
| **中** | **FakeVLM** | **公式OSSあり**。citeturn14search3 | clean detectionは強いが、R1論文ではJPEG/blur弱点が明確。citeturn17view3 | 高 | R1比較用。単独productionは非推奨 |
| **中以下** | **generic Qwen2.5-VL / InternVL / LLaVA zero-shot** | 容易 | RRDataset/FakeClueでは専用fine-tuneに大きく劣る。citeturn6view0turn16view4 | 低～中 | **主検出器としては非推奨** |
| **低** | **SAFE / FatFormerをSNS主軸にする** | OSS系あり | SAFEはRRDataset transmission fake 0.88%、FatFormerも最新OODで限定的。citeturn6view0turn10view2 | 低 | 比較baselineに留める |
| **停止推奨** | **UFD/CF/CuReの単純ORを最終判定とする** | 現状あり | ご提示実測ですでに崩壊。文献上もlocal/pixel shortcutのSNS fragilityが確認される。citeturn19view1 | 低 | score featureとして残すのは可、final ORは外す |

実装順としては、**第一段階でSo-Fake-R1とGlobalForgeを現在の586 real / 115 fakeへそのまま通し、必ず同一の1024＋JPEG75版で`TPR@FPR` curveを取得する**のが最も情報量が大きいです。So-Fake-R1は今回のSNS条件への直接性、GlobalForgeは局所artifact shortcutを捨てる設計という点で、現在のUFD/CF/CuReとは失敗モードが異なります。citeturn22search2turn19view1

次にreal群を最低**2,995独立群**まで増やし、FPR 0.1%の片側95%証明を可能にします。その上で、So-Fake-R1 semantic score、GlobalForge score、現行3 detector score、provenance result、画像処理categoryを特徴量として**calibrated fusion**を学習するのがよいでしょう。単純ORではなく、scoreのtailを直接最適化し、validation objectiveを`TPR@FPR=0.001`に置くべきです。

最終的な2026年時点の技術判断は、**「AI画像検出は終わった」のではなく、「clean-image fingerprint classificationをSNS画像へそのまま持ち込む方式が終わった」**に近いです。RRDataset、So-Fake、GlobalForge、NTIRE 2026が共通して示しているのは、実運用ではgenerator fingerprint単独から、**degradation-stable global structure、semantic/physical reasoning、明示的degradation training、provenanceの融合**へ移行する必要がある、ということです。citeturn22academia16turn22search4turn19view1turn22search1

そして、ご提示の条件で最も重要な未解決点はモデル選定そのものではなく、**「FPR 0.1%というscore distributionの最端部で、GPT Image 2／Nano Banana級のSNS再圧縮画像を90%以上拾えるか」について、公開研究がまだほぼ答えていないこと**です。現時点で最も妥当なmodern replacementは、**So-Fake-R1型VLM reasoning＋GlobalForge/DCPT型robust visual expert＋C2PA/soft-binding/watermark＋低FPR専用calibration**という多段構成です。