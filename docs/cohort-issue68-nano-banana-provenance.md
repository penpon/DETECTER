# Nano Banana系のprovenance実測 (Issue #68 Phase 0-1)

2026-09-26。`ai-picture/nano-banana-001〜005.png` (Higgsfield経由生成) を対象に、
Geminiアプリ検証、OpenAI Content Provenance API、ファイルメタ確認を行った。

## ファイルメタ (ローカル確認)

PNGの XMP/IPTC チャンクを確認した結果、**56枚中47枚に「Made with Google AI」
クレジット + `trainedAlgorithmicMedia` (Iptc4xmpExt:DigitalSourceType) が残存**する。
ない9枚 (002, 019, 021, 022, 024, 025, 036, 052, 055) はHiggsfield側でメタが
剥がれたと推測 (再ダウンロードしたオリジナルでも同じく欠落を確認)。
このメタはSNS加工で剥落するため透かしの代替にはならないが、**元画像のままなら
ローカルでGoogle由来を検出できる**。

## Geminiアプリ検証 (手動5枚)

| 画像 | Gemini判定 | 正解 | 結果 |
|---|---|---|---|
| 001 住宅街夕暮れ | 実写写真 | AI生成 | 見逃し |
| 002 棚田と桜 | AI生成 (季節矛盾・絵画質感) | AI生成 | 検出* |
| 003 駅発車案内 | AI生成 (スペルミス) | AI生成 | 検出* |
| 004 公園ベンチ | 実写写真 | AI生成 | 見逃し |
| 005 夕暮れ住宅街 | 実写写真 | AI生成 | 見逃し |

*検出2件は意味的矛盾への推測判定。SynthID透かし検出の明示なし。

## OpenAI Content Provenance API (Nano Banana 001-003)

```
001: c2pa=not_detected, synthid=not_detected
002: c2pa=not_detected, synthid=not_detected
003: c2pa=not_detected, synthid=not_detected
```

OpenAI APIはOpenAI系信号のみを見るため、Nano BananaのSynthIDは検出対象外。
実写の証明にもならない。

## Google側の検証経路

- Geminiアプリ: 意味判定と透かしが混在し構造化値が取れない。10回/日制限。
- AI Content Detection API (組織向け): private preview募集停止中 (2026-09時点)。
- → **現時点でNano BananaのSynthIDを透かしとして明示検出する外部経路はない。**

## 結論

- **Nano Banana系はGoogle AIメタ (XMP) が残っているうちはローカルで検出できるが、SNS加工後は落ちる。**
- **Google SynthIDの透かし検出経路は現状実質ないため、Nano Banana系は受動検知に頼るしかない。** Issue #68のPhase 2 (受動検知パイロット) の必要性は残る。
- GPT Image 2系のみが構造化provenance検出 (OpenAI API) の対象。

## 成果物

- `results/synthid-manual.jsonl`: Gemini手動検証記録5件
- `docs/evidence/synthid-nano-banana-20260926.md`: 判定文言転記
- 本ファイル
