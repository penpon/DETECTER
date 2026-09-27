Geminiアプリ SynthID検証の手動記録 (2026-09-26)
=============================================

検証方法: Geminiアプリ (gemini.google.com) で各画像をアップロードし
「この画像はAI生成ですか？」と質問。回答内容を転記。

重要な注意: Geminiの回答は「AI生成か実写か」の意味判定を含む。
SynthID透かし検出と、画像内容からの推測判定を区別する必要がある。

全5枚とも receipts/ に Higgsfield経由 Nano Banana 生成記録がある
(正解ラベル: 全てAI生成)。

--- nano-banana-001.png (Tokyo住宅街夕暮れ) ---
Gemini判定: 実写写真 (本物の写真) と回答
根拠文言: 電柱・配線・自転車・室外機等の細部構造に破綻なし、
雨上がりアスファルトの夕焼け反射が物理的に正確、等を挙げて実写と判定。
正解: AI生成 (Nano Banana)
→ 見逃し (false negative)

--- nano-banana-002.png (棚田と桜) ---
Gemini判定: AI生成画像
根拠文言: 満開の桜と青々と育った稲の苗の季節的矛盾、山脈の作為的な
鋸歯状、人物の足元が水面に不自然に溶け込む、等を挙げてAI生成と判定。
正解: AI生成 (Nano Banana)
→ 正検出 (意味的矛盾からの推測。SynthID透かし検出とは限らない)

--- nano-banana-003.png (駅発車案内板) ---
Gemini判定: AI生成画像
根拠文言: 「PLATROM」スペルミス、「TRACK」ヘッダーの重複、
フォント太さ・人物境界の歪みを挙げてAI生成と判定。
正解: AI生成 (Nano Banana)
→ 正検出 (意味的矛盾からの推測。SynthID透かし検出とは限らない)

--- nano-banana-004.png (公園ベンチ) ---
Gemini判定: 実写写真 (本物の写真) と回答
根拠文言: ベンチ木目・鋳鉄アームの対称曲線・芝生の自然な摩耗痕跡、
木漏れ日と被写界深度の自然さを挙げて実写と判定。
正解: AI生成 (Nano Banana)
→ 見逃し (false negative)

--- nano-banana-005.png (夕暮れ住宅街) ---
Gemini判定: 実写写真 (本物の写真) と回答
根拠文言: 電柱上の変圧器・腕金・高圧線等の配線が施工基準通りに精緻、
自転車スポーク・室外機等の細部に破綻なし、と実写判定。
正解: AI生成 (Nano Banana)
→ 見逃し (false negative)

集計: AI生成5群中、detected 2 / not_detected 3。
検出された2件はいずれも画像内容の意味的矛盾 (スペルミス・季節矛盾) を
根拠にした推測判定であり、SynthID透かしビットの検出を明示していない。
透かし検出率としては最大でも 2/5、内容推測を除けば透かし由来の
確定検出は確認できなかった。

追記 (2026-09-26): OpenAI Content Provenance API をNano Banana 001-003に送信。
  001/002/003 いずれも c2pa=not_detected, synthid=not_detected。
  → OpenAI APIはOpenAI系信号のみを見るため、Nano BananaのGoogle SynthIDは
    そもそも検出対象外。実写の証明でもない。
  → 写真メタには 001/003/004/005 に XMP「Made with Google AI」+
    trainedAlgorithmicMedia が残っているが、OpenAI APIはそれを拾わない。
  → Nano BananaのSynthID検出にはGoogle側の検証経路 (Geminiアプリ) が必要。
    ただし募集停止中のAI Content Detection APIを除く。
