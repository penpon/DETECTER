# 確定バイパスとEXIFサニタイザー

検証済みの能動的来歴だけが受動モデル推論をスキップし、`ai_probability` を
0.0（実写確定）または 1.0（AI確定）で即座に確定します。

## 確定ルール（`detecter.core.deterministic_bypass`）

- C2PA署名が `confirmed`（署名・信頼アンカー・画像一致を確認）かつ
  Secure Enclave / StrongBox 由来のハードウェア署名で、AIクレームがない
  → `ai_probability: 0.0`、`state: real_confirmed`。
- `confirmed` なC2PAにAI生成・編集クレーム（actions / c2pa.ai-disclosure）がある
  → `ai_probability: 1.0`、`state: ai_confirmed`。
- SynthID透かしが自動検証つきで `detected` → `ai_probability: 1.0`。
  手動登録の画面結果（`automatically_verified: false`）はバイパスしません。

バイパスしない場合、受動モデルの暫定判定がそのまま使われ
`ai_probability` は `null`（未確定）です。

## EXIFサニタイザー（`detecter.core.inspect_exif_sanitized`）

構造化カメラ情報（Make/Model/露出/F値/ISO/焦点距離等）だけを抽出します。
UserComment、ImageDescription、Artist、XP系、メーカーノート等の
自由記述フィールドは読み取り結果に含めず、プロンプトインジェクションを
物理的に遮断します。

AppleのSmart HDR / Deep Fusion等の処理痕跡（HDR Gain Map、CompositeImage、
メーカーノートの処理ラベル）を検出すると
`computational_photography_detected` を true にします。
後続レイヤーはこのフラグで実写写真の誤爆を抑制できます。

署名のないEXIFは `signed: false` / `proof_of_real: false` を常に返し、
実写の絶対的証明としては重みゼロです。
