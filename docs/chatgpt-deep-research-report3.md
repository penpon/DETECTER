# 劣化耐性AI画像検出器の追加学習計画は、2026年9月時点でモダンか

## 判定サマリー

| 仮説 | 判定 | 2026-09-26時点の結論 |
|---|---|---|
| **H1. DCPTは依然として最先端の劣化不変学習か** | **不成立** | clean/degradedペアを使う発想自体は依然有効だが、7月公開の **GlobalForge** は劣化不変contrastive lossに加え、局所shortcut抑制とglobal reasoningを導入し、単一・複合劣化でより広い検証を行っている。さらにDCPT原論文には、**frozen backbone上のfeature-consistency lossが論文記述どおりなら学習可能パラメータへ勾配を持たない**という再現上の重大な疑問がある。DCPTをそのまま「SOTA」として採用するのは勧めない。citeturn23view0turn25view0turn25view2turn25view3 |
| **H2. So-Fake-Setは現時点で最適な学習データか** | **一部成立** | 非常に有力だが、単独最適ではない。現行HF版は **2,225,740行・1.28 TB**、論文v5ではSo-Fake-Setは30手法、OODは15の分離された商用手法、全体45手法。HF viewerの`generator`は32値なので「32生成器」はメタデータ上は見えるが、現行論文の正式な数え方とは一致しない。50GB環境では全量利用は非現実的。citeturn27view0turn27view1turn27view3turn28view0turn28view3 |
| **H3. 自前の追加学習はまだ必要か** | **証拠不足** | **いきなり学習を始める根拠は弱くなった**。公開passive detectorで「GPT Image 2 / Nano Banana × 1024+JPEG75 × FPR≤0.1%」を無学習で解いた一次報告は今回の調査範囲では見つからなかった。一方、2026年後半はprovenanceが大きく進展し、OpenAIは画像のC2PA+SynthIDをAPI検証可能、GoogleもNano Banana系列全生成画像にSynthIDを付与し検証手段を拡充している。したがってまずprovenance層を完成させ、その残差だけpassive detectorで取るべき。citeturn30search0turn30search2turn31search0turn31search2 |
| **H4. 3位LPTから要素を借りるのは正しいか** | **一部成立** | **LoRA + clean/degraded pairwise optimization**はパイロット向けに妥当。ただしNTIRE 2026 Robust AUCは1位0.9723、2位0.9721に対しLPTは0.9251で、明確な差がある。1・2位の強みは大規模データ、DINOv3、強い劣化augmentation、ensemble/TTA。巨大モデル部分はCPU運用に不適だが、**augmentation/data strategyはLPT以上に借りる価値がある**。citeturn32view2turn32view3turn32view4 |
| **H5. 低FPRで追加学習の効果は立証されているか** | **証拠不足** | DCPTはAccuracy/AUC、GlobalForgeはBAcc、NTIREはROC-AUC中心で、**FPR≤1%、特に0.1%でreal score右裾が縮むことを直接示していない**。2026年の画像ベンチSynCred-Benchは固定FPRを採用したが5%まで。0.1%を真正面から扱う強い2026年例は動画分野であり、画像については研究上の空白が残る。citeturn23view0turn25view3turn32view1turn21academia6turn21search3turn21academia7 |
| **H6. より単純な代替で同等以上にできるか** | **一部成立** | **provenance-firstは必須の代替候補**。一方、単なる閾値再較正や単調calibrationはROC順位を改善しないので、現在のpassive detectorが0-FP点でほぼ検出不能というご提示実測を根本解決する保証はない。TTAはNTIRE上位でも使われるが推論コストを増やし、0.1% FPRでの改善は未立証。selective predictionは有用だが、abstainを除外して見かけのFPRを良くする評価は禁止すべき。citeturn32view3turn30search0turn31search0 |

**総合判定は「一部差し替え」**である。

計画の中心思想、すなわち「実運用の劣化を学習時に明示的に扱い、生成器OODで評価する」は2026年9月でも十分モダンである。しかし、**「DCPTそのものを主手法」「So-Fakeの4劣化を学習中に再現」「So-Fake-R1の70前後を継続基準」**という3点は差し替えるべきである。DCPTは **paired CE + prediction consistencyを第一候補**に縮約し、必要ならGlobalForge型contrastive lossを追加する。データはSo-Fake全量ではなく **So-Fake-Setの層化subset + NTIRE 2026 train subset + 自前hard-real** にする。そして継続基準はaccuracy 70ではなく、最初から **group-level TPR@FPR=1% / 0.1%とその信頼区間**に統一する。citeturn25view0turn25view3turn27view2turn32view0

さらに重要なのは、**GPU学習をPhase 1にしないこと**である。ご提示のOpenAI provenance実測31/31を踏まえると、まずGPT Image系はprovenanceで処理し、Nano Banana系列についてGoogle SynthIDを同じSNS加工条件で測る。この2系列だけが当面のターゲットなら、そこで十分なcoverageが得られれば、追加学習のROIは大幅に低下する。GoogleはNano Banana 2を含むGemini画像生成について「all generated images include a SynthID watermark」と明記している。citeturn31search1turn31search2turn31search6

## DCPTと2026年後半の劣化耐性研究

### DCPT原論文を厳密に読むと、主張より限定的

DCPTは2026年4月11日公開、5月26日改訂の6ページ論文である。学習データはB-Free公式セットの **MS-COCO real 51,517枚 + Stable Diffusion 2.1 fake 51,518枚**。評価はSynthbusterの9生成器9,000枚とCOCO real 1,000枚で、JPEG QF 30/50/70、Gaussian blur、resizeを評価する。主指標はAccuracy、副指標がAUCで、**TPR@FPRは報告されていない**。citeturn18view1turn23view0

比較の核心は「B-Freeそのもの」ではない。B-Free公式モデルはDINOv2 ViT-B/14をend-to-endで86.5Mパラメータfine-tuneし5-crop inferenceするのに対し、DCPT実験では**DINOv2 ViT-B/14を完全freezeし、197Kパラメータの2層MLP classifierだけを学習**している。DCPTの+9.1ptは、この小さいfrozen-backbone baselineに対する改善である。B-Free公式値は参考上限として別条件で掲載されている。citeturn23view0turn24view0

実数ではbaselineのdegraded average Accuracyが64.0%、DCPTが73.1%。JPEGはQ70で56.8→72.5、Q50で53.3→71.2、Q30で52.3→69.5となる。一方cleanは86.2→85.3で0.9pt低下する。したがって「JPEGに効いた」という観察自体は論文表と一致する。citeturn24view0turn25view1

ただし、**ここに再現性上の重要な問題がある**。論文はbackboneを固定し、

\[
f_c=\phi(x_c),\qquad f_d=\phi(x_d)
\]

としたうえで、その**backbone出力同士**にcosine feature loss \(L_{\rm feat}\) を置く。学習可能なのは後段classifier \(g\) だけである。論文記述どおりなら \(L_{\rm feat}\) は \(g\) に依存せず、frozenな \(\phi\) にも更新を掛けられないため、**学習可能パラメータに対する勾配はゼロになる**。これは論文の数式とfreeze条件から直接導かれる数学的推論である。citeturn23view0turn25view0

にもかかわらず、Table IIでは「\(L_{\rm feat}\) only」がJPEG平均を54.1→70.7まで改善したとされる。ただしDCPT側の総損失にはcleanとdegradedの両方のCEがあり、baselineはpaired trainingを使わないため、**「degraded-view CEだけを加え、consistencyをゼロにしたpaired-CE-only」対照実験がない**。したがって、この+16.6ptをfeature lossそのものに帰属させることは、公開されたアブレーションだけではできない。さらにJPEG平均だけなら \(L_{\rm pred}\)-onlyが72.9で、full DCPTの71.1を上回る。citeturn25view0turn25view1

これはDCPTを捨てる理由ではないが、**そのまま再実装する理由は弱める**。実用パイロットでは、

\[
L =
CE(x_c,y)+CE(x_d,y)
+\lambda_{\rm pred} KL(p_c,p_d)
\]

を最初のDCPT系baselineにして、feature lossを使うなら**LoRAで更新されるbackbone出力、またはtrainable projection headの後**に置くべきである。そうすればlossが本当に表現を動かす。

公開状況も注意点である。arXivページには公式GitHubへの直接リンクがなく、コード検索サービスも「Request Code」の状態で、今回の調査では著者公式実装を確認できなかった。したがって、DCPTの数値をそのまま再現性の高い基準値とは扱わない方がよい。citeturn18view2turn26search2

### GlobalForgeはDCPT後の直接的な上位候補

2026年7月16日公開の**GlobalForge**は、今回見つかった中ではDCPTを最も直接的に古くした研究である。発想は、JPEG等で消えやすい局所生成artifactに頼ること自体を問題視し、Local Information Bottleneckでlocal high-frequency shortcutを抑制し、Global Structural Reasoningで近傍tokenへの依存を禁止し、遠距離構造を統合させるというもの。さらにclean/degraded表現に**symmetric InfoNCE型のDegradation-aware Contrastive Structural loss**を掛ける。citeturn19view1turn25view2

評価もDCPTより実運用寄りである。RealDeg-BenchはJPEG、blur、resize、noise、brightness、contrast、saturationの7原子劣化に加え、1〜5個を連結したcompound degradationを持つ。計95,589枚で、別途Chameleon、SynthWildX、WildRF、AIGIBench、CO-SPY、**RR-Dataset**、BFree-Online、real-chainという8群のin-the-wild評価も行う。citeturn24view1turn25view3turn25view4

RealDeg-Bench平均BAccではDINOv3系GlobalForgeが85.81%、GAPL 82.13%、B-Free 80.90%、DDA 80.30%。5段compound degradationでも79.53%を維持する。一方、論文の主要指標はあくまでBAccであり、FPR 0.1%での性能ではない。DCPTとの直接head-to-headも行われていないため、「GlobalForgeがあなたの動作点でDCPTを上回る」とまでは言えない。citeturn24view2turn25view3

またGlobalForgeはLIB/GSRという推論時architectureを持つため、**「zero inference overhead」というDCPTの利点は失う**。CPU常用という条件では、GlobalForgeを丸ごと置換するより、まずその**degradation-aware contrastive objectiveだけをtrainable featureに移植する**のが合理的である。コードは公開されているものの、2026-09時点では匿名4open.scienceリポジトリであり、成熟した長期保守GitHub実装とはまだ言いにくい。citeturn19view1turn33academia41

したがってH1に対する実務的な結論は、**「DCPT full」ではなく「paired trainingという原理を残し、DCPT-LpredとGlobalForge-contrastiveを比較する」**である。

## So-Fake、NTIRE、実SNS劣化のデータ設計

### So-Fake-Setの公称値は一部アップデートが必要

So-Fake論文は2026年7月31日にv5へ更新されている。現行論文ではSo-Fake-Setを「約2M、12カテゴリ、real/full synthetic/tampered、**30のsynthesis/editing models**」と定義し、So-Fake-OODは100K規模、5ソーシャルプラットフォーム由来のrealと、**学習側と完全にdisjointな15商用generator**で構成する。全体では45のgeneration/editing methodsを使う。citeturn27view0turn27view3

一方、実際のHugging Face公開物は**2,225,740行、1.28 TB**で、viewer上の`generator`フィールドは32値を持つ。したがってご依頼文の「約223万枚、32生成器」はHF実体を指すなら理解できるが、**論文v5の正式なgenerator-method countは30（Set）+15（OOD）**である。数値を報告書等で使うなら、この区別を明記すべきである。citeturn28view0turn28view3

dataset cardは明示的に**Creative Commons Attribution 4.0 International**と記載している。citeturn28view2 ただしSo-Fake-SetのrealはCOCO、Flickr30k、OpenImages、WIDER、CelebA、OpenForensics、FFHQなどから集められている。これは「So-Fakeのdataset cardがCC BY 4.0を掲げている」という事実とは別に、実運用・再配布・商用利用時には各upstream sourceの条件も確認するのが安全、というライセンス上の実務的注意点である。これは法的判断ではない。citeturn27view1

50GB制約の下では1.28TBを丸ごと置く方針は成立しない。むしろSo-Fakeはsource-image単位でgroup splitしてcontent leakageを避けているため、**generator × semantic category × source dataset × real/full-syntheticを層化してsubset化**する方がパイロット目的に合う。citeturn27view1

また、対象が「完全生成 vs 実写」であるなら、So-Fake全量の約3分の1を占める**tamperedを主タスクのfakeとして無条件に混ぜない**方がよい。So-Fake自身がREAL / FULL_SYNTHETIC / TAMPEREDを分離した三値protocolを採用しているからである。citeturn27view0turn27view1

### 「So-Fakeの4劣化を学習中に再現」は前提を修正すべき

ここは重要な訂正点である。現行So-Fake論文で示される4種類は、**4つのdiffusion加工ではなく、So-Fake-OODに後付けして評価するcontrolled social-media propagation chains**である。具体的には、

- Re-enc.: 長辺1024 + JPEG Q75
- Web Dist.: 1024 resize → WebP Q80 → JPEG Q85
- Repost: 1080×1920 canvas → JPEG Q80 →再resize
- Cross-Plat.: 1280 resize → JPEG Q85 → WebP Q80 →1024 resize →JPEG Q75

である。citeturn27view2

そしてSo-Fake-R1の数字はClean 72.0、Re-enc. 69.5、Web Dist. 68.2、Repost 67.0、Cross-Plat. 65.9だが、**Table Xの指標は“Detection accuracy”である**。TPR@FPRではない。したがって、

> 「So-Fake-R1 OOD≈72、1024+JPEG75≈70以上なら継続」

をあなたの主指標のacceptance criterionにするのは不適切である。citeturn27view2

これは今回の計画で最も修正優先度が高い点の一つである。FPR≤0.1%が運用要件なら、69.5% accuracyのモデルがその動作点でTPR 60%なのか、10%なのか、0%なのかはこの表から分からない。

さらに実SNS伝送に対しては、So-Fakeの4chainだけでは不十分である。GlobalForge自身も、controlled RealDeg-Benchとは別にRR-Datasetやreal-chain等をin-the-wild suiteとして評価し、**合成劣化と自然に生じたplatform propagationを別物として扱っている**。citeturn25view3

したがって推奨は、学習augmentationを「So-Fakeの4chainの模倣」に固定せず、

**実際の対象SNSで upload → download / screenshot → save → repost を実測した経験分布**
+
**1024/Q75を中心としたランダム化synthetic degradation**
+
**少量のcompound degradation**

にすることである。特に1024/Q75だけを固定して学習すると、Q75 encoder実装やchroma subsampling、resize kernelなどをshortcutとして学ぶ危険がある。

### GPT Image / Nano Bananaを本当にOODにできるか

So-Fake v5は、So-Fake-Setの30手法とSo-Fake-OODの15商用手法を**完全disjoint**にしたと明記し、本文ではGPT-Image-2、Seedream 4.5、Nano-Banana-2のような新しい商用モデルをsocial-media環境の例として明示している。したがって**So-Fake-Setだけを学習に使い、So-Fake-OODを一切触らなければ、最新商用モデルに対するgenerator-OOD設計は成立する**。citeturn27view0turn27view1

NTIRE 2026も同じ思想をより明確に採用した。trainは約277K、20のopen-source generator。一方Validation HardにはNano Banana、public testにはNano Banana Proが入り、より新しいproprietary generatorを後段splitに予約した。challenge全体では42 generator、36種類のtransformationを使用する。citeturn32view0turn32view5turn33view1

よってパイロットでも、**GPT Image 2系58群とNano Banana系57群を学習データへ混ぜてから同系列で評価してはいけない**。それを行う場合は「OOD性能」ではなく「target-domain adaptation性能」と名前を変え、別の未使用version/time-splitを最終評価に確保する必要がある。

## NTIRE上位手法、公開検出器、provenanceという代替

### NTIRE 2026ではLPTは「省資源な3位」ではあるが、性能上の最適解ではない

公式CVPR 2026 NTIRE workshop結果は以下の通りである。challengeの主指標は**Robust ROC AUC**であり、低FPR指標ではない。citeturn32view1turn33search5

| 順位 | 手法 | 平均 Robust ROC-AUC | 主な構成 | あなたとの適合性 |
|---|---|---:|---|---|
| 1位 | MICV | **0.9723** | multi-source百万枚級データ、複数DINOv3 committee、difficulty-aware augmentation、Focal Loss、SWA | 性能設計は参考になるが規模過大 |
| 2位 | Ant International | **0.9721** | DINOv3-7B ×2、full fine-tune、4段階劣化augmentation、TTA、ensemble | CPU運用には事実上不適 |
| 3位 | TeleAI-TeleGuard LPT | **0.9251** | EVA-CLIP + LoRA、clean/degraded pair、KL + feature MSE、追加実劣化、So-Fake/Chameleon | **要素借用には最も現実的** |

順位・スコアは公式表による。citeturn32view4

2位Antのモデルは2つのDINOv3-7B、合計14BパラメータをB200でfull fine-tuneし、推論でもA100上78.25GB VRAM、約2.21 image/sである。これをCPU常用環境の候補にするのは合理的ではない。citeturn32view2turn32view3

LPTはEVA-CLIPのMHSA/FFN linear layerをLoRAでadaptし、cleanとdistortedを同一batchへ入れ、

\[
L=CE+\alpha KL+\beta MSE_{\rm feature}
\]

を使う。Speckle Noise、Color Cast、Organic Moiréをvalidation観察後に追加し、8×A800で5 epoch学習している。つまり「LoRAだから非常に軽い」というほど小規模ではないものの、**目的関数の移植性は1・2位より高い**。citeturn32view3

一方、1位の教訓はarchitectureよりも、**異種データ源・最新generator・難易度別augmentation・SWA**である。2位の教訓も、4レベルのclean/mild/moderate/heavy augmentationと、robustness specialistを分離した点にある。citeturn32view1turn32view2

したがってLPTを選ぶ理由は、

> 「3位だから強い」

ではなく、

> **「pairwise consistencyをLoRAで実装でき、DCPTよりtrainable representationにlossを掛けやすく、1・2位の巨大ensembleよりパイロットへ縮小しやすい」**

であるべきである。

公開性にも差がある。Ant InternationalのNTIRE DINOv3-7B weight/inference資材はHugging Faceに公開されている。citeturn33search4turn33view2 一方、今回の検索ではMICVまたはTeleAI-LPTの「公式で、そのまま再現できる完成checkpoint + training repository」は明確に確認できなかった。GlobalForgeは匿名コード、DCPTは公式コードリンク未確認である。したがって**論文順位だけでなく、再現可能性を重視するとLPTを自作縮小版として実装する方が現実的**である。

### ただし2026年後半は「透かしを先に見る」が大きく強くなった

ここは当初計画を最も大きく変える2026年後半の動きである。

OpenAIは2026年にContent Provenanceを拡充し、現在のAPIは画像について**C2PA Content CredentialsとSynthID**を検証できる。OpenAI自身が「一般的AI detectorではなく、supportされたOpenAI provenance signalを調べるもの」と明記しており、`not_detected`はrealの証明にはならない。一方、検出されたsignalはspecific provenance evidenceとして扱える。citeturn30search0turn30search1

さらにOpenAIは2026年5月からGoogle DeepMind SynthIDを画像に組み込み、7月にはverification APIへ拡大した。公式説明ではSynthIDはC2PAより変換耐性を持ち、crop、filter、lossy compression等に耐えるよう設計される一方、実際の変換によって弱まる可能性もある。citeturn30search2turn30search3

したがって、ご提示の

> GPT Image 2系、SNS加工後31/31 SynthID detected、real 0 FP

という自前実測は、研究上のBAcc改善より**はるかに運用価値の高い結果**である。

Nano Bananaについても状況はかなり変わっている。Google公式Gemini API docsは**Nano Banana 2を含む生成画像すべてにSynthID watermarkが入る**と明記する。Geminiアプリでは画像をアップロードしてSynthID verificationが可能で、Googleは2026年に組織向けAI Content Detection APIも発表している。ただし後者は少なくとも発表時点ではtrusted partnersを起点とした展開であり、誰でも同条件でproduction APIを利用可能かは契約・アクセス条件の確認が必要である。citeturn31search0turn31search2turn31search3

これはH3/H6の優先順位を変える。

**対象生成器が当面GPT Image系とNano Banana系だけなら、まず両者のwatermark coverageを実SNS経路で測り切るべきであり、その結果次第では自前passive detectorの追加学習そのものを延期または中止できる。**

ただしpassive detectorを完全廃止するのもまだ早い。OpenAI自身が、compression、cropping、screenshot、metadata removal、legacy output等によってsignalが失われ得ること、他社AIを一般検知するAPIではないことを明記している。Google側もSynthIDはGoogle AI provenanceを示すものであり、未知generator一般のreal/fake分類器ではない。citeturn30search0turn31search3

したがって2026-09時点で最も自然なのは、

\[
\text{Provenance detector}
\;\rightarrow\;
\text{strict passive detector}
\;\rightarrow\;
\text{abstain / review}
\]

という三層構成である。

## 低FPR評価では、現在の586 real群ではまだ判定できない

### 文献側の最大の穴はまさにFPR 0.1%

DCPTの主指標はAccuracy、GlobalForgeはBAcc、NTIRE 2026はROC-AUCである。つまり、いずれもあなたが必要としている**real score distributionの99.9 percentile付近**を直接最適化・評価していない。citeturn23view0turn25view3turn32view1

画像分野で2026年6月に出たSynCred-Benchはこの問題を認識し、FP450というreal-negative setと固定FPR評価を導入した。しかし厳しい動作点でもFPR=5%であり、そこですら15のMLLM平均TPR 10.5%、open-source AIGC detectorは5%未満、commercial APIは57.6%だった。対象分布はsynthetic credibility/document-like imagesなのであなたの写真分布とは違うが、**高い通常指標とdeployable threshold性能を混同してはいけない**という証拠にはなる。citeturn21academia6turn21search1

FPR=0.1%を明示する2026年の強い評価研究は動画側にある。ECCV 2026のSPLITはFake Recall@FPR={0.1%,1%,5%}、real-only threshold calibration、cross-real threshold transferを明示し、VidAuditも0.1% FPRでは高AUC detectorの一部がsingle-digit recallへ落ち、rankingが変わると報告する。**これは画像への性能移植を意味しないが、評価protocolとしては非常に参考になる**。citeturn21search3turn21academia7

今回調べた範囲では、**DCPT/LPT/GlobalForgeについて「学習後にreal scoreの右裾が縮み、TPR@FPR≤1%が改善した」と直接示す画像研究は確認できなかった**。したがってH5は明確に「証拠不足」である。

### 586 real群ではFPR 0.1%を統計的に保証できない

現在のreal 586群では、false positive 1群が

\[
1/586 = 0.1706\%
\]

である。したがって経験的FPRを0.1%刻みで測ること自体ができない。

さらに0/586 FPだったとしても、独立groupをBernoulli trialとみなしたとき、真のFPRに対する**片側95%上限は約0.51%**になる。つまり「観測上0 FP」と「FPR≤0.1%を95%信頼で示した」は全く違う。

0 FPを観測した場合に「真のFPRが0.1%以上なら、この0 FPという結果が起きる確率は5%以下」とするには、

\[
(1-0.001)^n\le0.05
\]

より最低 **2,995 independent real groups** が必要である。99%信頼なら約4,603群になる。

従って586群は**モデル間の荒い順位付けやhard-negative discoveryには十分有用**だが、0.1% FPRの最終認証セットとしては不足している。

生成側115群についても、真のTPRが70%程度なら標準誤差は約4.3pt、単純な95%近似区間は約±8.4ptである。GPT系58、Nano Banana系57へ分ければさらに広がる。5pt程度の改善をgenerator単位で判定したいなら、70%付近では概ね**300群強/生成器**が必要になる。

したがってpilotの二段階化を勧める。

**探索gate**では現在の586 real / 115 fakeを使い、改善が10pt級あるかを見る。**最終go/no-go**ではrealを少なくとも3,000独立群、できれば10,000群以上まで増やす。10,000群なら0.1% FPRで期待FP数が10件程度になり、右裾の挙動をようやく直接観察しやすくなる。

### threshold calibrationも評価から独立させる

最低でもデータを、

**train → calibration → locked test**

の三つへ分離する必要がある。

calibration realで99.9 percentile付近のthresholdを決め、それをlocked real/fakeへ一回だけ適用する。最終testでthresholdを動かすとFPR 0.1%の意味が失われる。

group単位で、同一source image、同一prompt series、同一撮影burst、同一生成sessionをまたいでsplitしないことも重要である。So-Fake自身がsource-image groupingでcontent leakageを避けているのは、この理由から妥当な設計である。citeturn27view1

generator OODについては、

\[
\text{train generators}
\cap
\text{test generator families}
=
\varnothing
\]

を基本とし、さらに可能なら**model-version/time split**も行う。Nano Banana 2を評価するならNano Banana旧版でtrainして「unseen generator」と呼ぶのではなく、「same-family version shift」として別枠報告する方が厳密である。

## 推奨する差し替え後の計画

### まず学習前にやるべきこと

現状では、最小コストで最大の意思決定価値があるのは追加GPU学習ではない。

| 優先度 | アクション | 判定基準・理由 |
|---|---|---|
| **最優先** | **Nano Banana系57群にGoogle SynthID verificationを実施**。clean、1024+Q75、実SNS upload/download、screenshot、repostを分ける | GoogleはNano Banana系列へのSynthID付与を公式明記。これがGPT系と同等に残るなら、対象2系列に限ってはfine-tuningの必要性が大幅に低下する。citeturn31search1turn31search2 |
| **最優先** | OpenAI provenanceを31件から全GPT群へ拡張し、crop/WebP/screenshot/cross-platformも追加 | OpenAI APIはC2PAとSynthIDを区別して返すため、「C2PAが落ちてもSynthIDが残る」のかを個別記録できる。citeturn30search0 |
| **最優先** | FPR評価用real cohortを最低3,000群へ拡張 | 586群では1 FP=0.171%。0/586でも95%上限約0.51%で、0.1%要件を検証できない。 |
| **高** | 既存passive detectorを同一locked cohortで**threshold sweep**し、TPR@0.1%、1%を記録 | accuracy/AUC/0-FP一点だけでは、新モデルとの比較基準にならない。 |
| **高** | NTIRE/So-Fake/GlobalForge系公開weightを「学習なしbaseline」として一度だけGPU評価 | 公開研究の上限を先に把握すれば、不要なtraining pilotを避けられる。ただしAnt 14Bはdeployment候補ではなく研究上限。citeturn32view3turn33search4 |
| **高** | So-Fake-OODを**完全にtest-only**として固定 | 最新商用generatorとのdisjoint設計を壊さない。citeturn27view0turn27view1 |
| **中** | target SNSの実upload/download pipelineを自動収集 | controlled Q75と本物のplatform pipelineの差を測る。GlobalForgeもcontrolled benchmarkとin-the-wildを別評価している。citeturn25view3 |
| **中** | TTAは最後にablation | NTIRE上位で有効だがCPUコスト増。aggregate scoreのreal右裾も再calibrationする必要がある。citeturn32view3 |

### GPU pilotを行うなら、この最小構成を推奨

**データは全So-Fakeではなく、合計およそ5万〜10万real/fakeから開始**する。これは「最終SOTAを作る」規模ではなく、「pairwise objectiveがあなたの分布で右裾を改善するか」を見るための規模である。DCPT原実験自体が約51.5K real + 51.5K fakeで効果を主張しているため、pilotとして100K級は十分合理的な出発点である。citeturn23view0

So-FakeからはREALとFULL_SYNTHETICをgenerator/category/sourceで層化抽出し、TAMPEREDはまず外す。これにNTIRE 2026 trainから新しいopen-source generatorを補い、自前real hard negativesとしてiPhone画像、EXIFなし保存画像、スクリーンショットを追加する。NTIRE trainは最新proprietary generatorを後段splitへ予約する設計なので、OOD訓練源として相性がよい。citeturn32view0turn32view5

学習条件は少なくとも次の三本を**同一データ・同一seed群**で比較するべきである。

| Pilot | 学習目的 | 採用理由 |
|---|---|---|
| **A: paired-CE baseline** | clean CE + degraded CE | DCPTの効果が単にdegraded-view supervisionで説明できないか確認するため。原論文に欠けている最重要ablation。 |
| **B: paired-CE + prediction KL** | A + clean/degraded prediction consistency | DCPT Table IIではJPEG平均がfull DCPTより高い。feature-lossの勾配問題も避けられる。citeturn25view0 |
| **C: B + trainable-feature contrastive** | LoRA等で更新される特徴上にsymmetric InfoNCE | GlobalForgeの最も移植しやすい2026年後半要素。full LIB/GSRより推論コストを増やしにくい。citeturn25view2 |

LoRAを使うなら、LPT同様にvisual transformerのattention/FFNへ入れるのが自然である。**feature consistencyをfrozen encoder出力へ置かない**ことが重要である。citeturn32view3

劣化augmentationは固定Q75だけにせず、実測SNS分布を中心にJPEG quality、resize、WebP、canvas/screenshot、軽いcolor shift、必要ならmoireをrandomizeする。NTIRE 2026は最大36種を使い、上位手法ほど複数severityのaugmentationを強く利用したので、「基盤モデルを変える」より先にここを丁寧に合わせる価値が高い。citeturn32view1turn32view2

ただし**評価用の1024+Q75はtraining augmentationから独立した固定protocolとして残す**。実SNS replayも独立testにする。そうしないと「Q75を覚えた」のか「劣化一般に頑健になった」のか区別できない。

### 継続条件はSo-Fake-R1の「70」を捨てる

推奨go/no-goは次のようにする。

主指標は必ず、

\[
TPR@FPR=0.1\%
\]

次に、

\[
TPR@FPR=1\%
\]

とする。各々についてgroup bootstrapまたはbinomial confidence intervalを出し、GPT Image系、Nano Banana系、実SNS経路、1024/Q75、screenshotを別々に報告する。

**So-Fake-R1の72.0 / 69.5はaccuracyなので、継続閾値として使わない。** 外部比較値として別欄に残すだけにする。citeturn27view2

pilotの成功条件は「BAcc +x pt」ではなく、たとえば、

> locked hard-real calibrationで同じFPR上限を維持したまま、BまたはCがAよりtarget-generator TPRを統計的に明確に上げること

とする。

特にreal scoreの99.9 percentile、99.5 percentile、99 percentileを学習前後で記録すれば、「fake scoreが上がっただけ」なのか、「問題だったreal右裾が実際に左へ戻った」のかを分離できる。これはH5の研究上の空白を、あなた自身の実験で直接埋める設計になる。

### 最終的な推奨アーキテクチャ

2026-09時点で、この用途に私なら次の順で構成する。

**第一層はprovenance**。OpenAI Content Provenance APIのC2PA/SynthID、Google/Nano BananaのSynthIDを使う。positiveなら高信頼generated evidenceとして扱う。OpenAIはverification APIを正式提供し、GoogleもNano Banana画像のSynthID付与とverificationを公式化している。citeturn30search0turn31search2turn31search3

**第二層は小型passive detector**。provenance未検出だけを対象にし、極端に厳しいthresholdで動かす。学習する場合は、DCPTそのものではなく**LoRA/adapted backbone + paired CE + prediction KL**を最初の候補とし、GlobalForge型contrastive lossをablationで追加する。

**第三層はselective prediction**。中間scoreを無理にrealへ倒さず`unknown / review`にする。ただし評価ではabstain率を必ず報告し、abstainを分母から消してFPRを良く見せない。

TTAは第四候補でよい。threshold再較正は必須だが、それだけでROC rankingは改善しない。monotonicなPlatt/isotonic calibrationも同様に、確率解釈は改善できても本質的なTPR@fixed-FPRを作り出せない。したがって、ご提示の「UFD/CuRe等が0-FP点でほぼ全滅」という状況では、それらだけで問題が解決する可能性は低い。

**最終判断として、DCPT + So-Fake-Set計画を中止する必要はない。しかし、そのまま着手するのは2026年9月時点では最適ではない。** まずprovenanceでGPT Image/Nano Bananaの大部分を取れるかを確定し、その後に残差問題が十分大きければ、**DCPTを縮約したpaired prediction-consistency + LPT型LoRAを最小baseline、GlobalForge contrastiveを追加候補、So-Fake-Set subset + NTIRE 2026 train + 実SNS hard-realをデータ**とするのが、現在の公開研究・50GB制約・CPU推論・FPR≤0.1%という条件を最もよく両立する。

特に開始前に変更すべき三点は、**「full DCPT → paired-CE/Lpredを先に検証」「So-Fake 4-chainをtraining recipeとみなさない」「Accuracy≈70 → TPR@0.1% FPRへ完全移行」**である。この三点を直せば、計画は2026年9月の研究水準に十分追随している。