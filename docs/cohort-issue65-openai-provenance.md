# Issue #65: OpenAI来歴検証APIでGPT Image 2系のC2PA/SynthID残存を計測する

受動検知（UFD / Community Forensics / CuRe / EFFORT）はSNS相当加工後に構造的に死ぬことがIssue #60・#62で確定した。透かし（C2PA/SynthID）が加工後も残るなら、それが最強の証拠になる。OpenAIのContent Provenance API（C2PA + SynthID）をGPT Image 2系の生成画像とその加工バリアント、および実写の一部に送り、検出有無を計測した。

## 1. 実装

- `src/detecter/openai_provenance.py`: OpenAI Content Provenance APIへの個別送信、429リトライ（`MAX_RETRIES=8`、`_SLEEP_BASE=2.0`）、レスポンスからのC2PA/SynthID抽出、ローカルC2PAリーダーへのフォールバック、生成器×加工条件ごとの集計。
- `scripts/measure_openai_provenance.py`: 台帳（`image_id` / `sha256` / `path` / `generator` / `history`）を1行ずつ計測し、生のAPIレスポンスをJSON Linesで出力する。`--local-fallback` でAPIキーがなくてもローカルC2PA計測を継続する。
- `tests/test_openai_provenance.py`: レスポンス解析・集計・条件分類・APIキー欠落時の動作をテストする。

APIエンドポイントは `POST https://api.openai.com/v1/content_provenance_checks`、認証は `Authorization: Bearer $OPENAI_API_KEY`、ファイルは `multipart/form-data` の `file` フィールドで送信する。429 は `Retry-After` ヘッダーまたは指数バックオフで待機してリトライする。

## 2. API実行結果（2026-09-25）

`results/openai-provenance.jsonl` に168枚中67枚の実測レコードを残した（残りはレート制限の厳しさで未計測。各APIレスポンスは `openai.c2pa.outcome` / `openai.synthid.outcome` に保持）。

| 生成器 | 加工条件 | 画像数 | API C2PA detected | API SynthID detected |
| --- | --- | --- | --- | --- |
| gpt-image-2 | original | 15 | 0/15 (0%) | **15/15 (100%)** |
| gpt-image-2 | sns-q75 | 31 | 0/31 (0%) | **31/31 (100%)** |
| iphone-real | sns-q75 | 21 | 0/21 (0%) | 0/21 (0%) |

### 結果の解釈

- **SynthID は SNS相当加工後も100%残存**した。長辺1024pxへのリサイズ + JPEG Q75 再圧縮で検出は一切失われない。
- **C2PA マニフェストは元画像・SNS加工のいずれでもAPIレスポンス上 `not_detected`**。生成直後のPNGにもC2PAがAPI上埋め込まれていない（ローカルC2PAリーダーでは`signature_state: valid`、`ai_source_assertion: true`を確認したものの、API `results[].type=="c2pa"` の `outcome` は `not_detected` で返る）。
- **実写 (iphone-real) ではSynthID・C2PAともに誤検知0**。SNS加工後の実写21枚全てで偽陽性なし。
- なおAPI応答の `results` には `c2pa` と `synthid` の2項目が常に含まれる。So-Fake 4拡散加工は #62 で当環境実行不可と結論付けられており、本計測には含めていない。

### 実測の制約

- 168枚中67枚のみ計測完了。残り101枚（gpt-image-2 original 43, sns-q75 27, iphone-real sns-q75 31）は `rate_limit_exceeded` (`try again after ~2000s`) の反復で未完。APIのレート制限が非常に厳しく、urllib実装では429連発が解消しなかったため、最終盤は `curl -F file=@...` で個別送信して部分回収した。
- gpt-image-2の未計測分も既取得分と同一傾向 (SynthID 100%残存、C2PA不検出) が強く示唆される。

## 3. Smoke結果（ローカルC2PAリーダー）

`results/openai-provenance-smoke.jsonl`（3行）を `--local-fallback` で計測した生データ。ローカルのみのスモーク結果であり、本表のAPI計測とは別系統。

| 生成器 | 加工条件 | 画像数 | ローカルC2PA AI来源率 |
| --- | --- | --- | --- |
| gpt-image-2 | original | 1 | 1/1 (100%) |
| gpt-image-2 | sns-q75 | 1 | 0/1 (0%) |
| iphone-real | original | 1 | 0/1 (0%) |

- ローカルC2PAリーダーでは `gpt-image-2` オリジナルのマニフェストが `signature_state: valid`、`issuer: OpenAI OpCo, LLC`、`ai_source_assertion: true` で確認できたが、**API側では同じ画像に対して `c2pa.outcome: not_detected` が返る**。C2PA検出判定はAPIとローカルで不一致だった。
- SNS相当加工後はローカルC2PAでもAI来源を検出できなくなった。

## 4. 成果物

- `src/detecter/openai_provenance.py`
- `scripts/measure_openai_provenance.py`
- `tests/test_openai_provenance.py`
- `results/openai-provenance.jsonl`（OpenAI API実測の生データ 67レコード）
- `results/openai-provenance.summary.json`（上記テーブルの元データ）
- `results/openai-provenance-smoke.jsonl`（ローカルC2PA smokeの生データ 3レコード）
- `results/openai-provenance-smoke.summary.json`

## 5. 結論

- **GPT Image 2系の生成画像には SynthID が常に埋め込まれており、SNS相当加工（長辺1024 + JPEG Q75）後も 100% 検出**される。Issue #60・#62 で死んだ受動検知の代替として、SynthIDが最も強い残存信号である。
- **C2PA はAPI上 `not_detected` で一貫**（元画像・加工後とも）。ローカルリーダーでマニフェスト自体は読めるが、OpenAI Content Provenance API の `c2pa` エントリは検出扱いにならない。
- **実写で誤検知なし**（SynthID 0/21、C2PA 0/21）。
- レート制限により残り101枚（gpt-image-2 original 43, sns-q75 27, iphone-real sns-q75 31）が未計測。完了済みデータでは傾向が一貫しており、未完分も同方向と見込まれる。追加計測は `OPENAI_API_KEY` 設定の上で `scripts/measure_openai_provenance.py` を未計測台帳に向けて再実行すればよい。
