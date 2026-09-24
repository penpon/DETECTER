# Issue #65: OpenAI来歴検証APIでGPT Image 2系のC2PA/SynthID残存を計測する

受動検知（UFD / Community Forensics / CuRe / EFFORT）はSNS相当加工後に構造的に死ぬことがIssue #60・#62で確定した。透かし（C2PA/SynthID）が加工後も残るなら、それが最強の証拠になる。OpenAIのContent Provenance API（C2PA + SynthID）が公開済みであるため、GPT Image 2系の生成画像群とその加工バリアント、および実写の一部に同じAPIを送り、検出有無を計測する。

## 1. 実装

- `src/detecter/openai_provenance.py`: OpenAI Content Provenance APIへの個別送信、429リトライ、レスポンスからのC2PA/SynthID抽出、ローカルC2PAリーダーへのフォールバック、生成器×加工条件ごとの集計。
- `scripts/measure_openai_provenance.py`: 台帳（`image_id` / `sha256` / `path` / `generator` / `history`）を1行ずつ計測し、生のAPIレスポンスをJSON Linesで出力する。`--local-fallback` でAPIキーがなくてもローカルC2PA計測を継続する。
- `tests/test_openai_provenance.py`: レスポンス解析・集計・条件分類・APIキー欠落時の動作をテストする。

APIエンドポイントは `POST https://api.openai.com/v1/content_provenance_checks`、認証は `Authorization: Bearer $OPENAI_API_KEY`、ファイルは `multipart/form-data` の `file` フィールドで送信する。レート制限（429）は `Retry-After` ヘッダーまたは指数バックオフで待機してリトライする。

## 2. 実行時のAPIキー状態

実行環境に `OPENAI_API_KEY`、`.env`、または `receipts/` 内のキーは見つからなかった。したがって**OpenAI APIそのものへの計測は行わず**、実装とsmoke台帳を残し、APIキーが設定された後の1コマンドフォローアップとして計測できるようにした。

## 3. Smoke結果（ローカルC2PAリーダー）

`results/openai-provenance-smoke-ledger.jsonl`（3行）を `--local-fallback` で計測した生データを `results/openai-provenance-smoke.jsonl` に保存している。

| 生成器 | 加工条件 | 画像数 | API C2PA | API SynthID | ローカルC2PA AI来源率 |
| --- | --- | --- | --- | --- | --- |
| gpt-image-2 | original | 1 | 未実行 | 未実行 | 1/1 (100%) |
| gpt-image-2 | sns-q75 | 1 | 未実行 | 未実行 | 0/1 (0%) |
| iphone-real | original | 1 | 未実行 | 未実行 | 0/1 (0%) |

- `gpt-image-2` オリジナルにはC2PAマニフェストが存在し、`signature_state: valid`、`issuer: OpenAI OpCo, LLC`、`ai_source_assertion: true`、`generation_scope: full` がローカルで確認できた。
- SNS相当加工（長辺1024 + JPEG Q75）後はC2PAマニフェストが失われ、ローカルC2PAではAI来源を検出できなくなった。
- 実写（`iphone-real`）ではローカルC2PAでAI来源は検出されなかった。これは実写で誤検知が出ていないことを示唆するが、API未実行のため正式的な誤検知評価ではない。

So-Fakeの4拡散加工バリアントは #62 で当環境では実行不可と結論付けられたため、本smokeには含めていない。台帳に `history` で `sofakediffusion-*` 等の加工条件を入れれば、`scripts/measure_openai_provenance.py` は同じように計測する。

## 4. API実行時の1コマンドフォローアップ

`OPENAI_API_KEY` を環境変数または `--api-key` で渡し、対象台帳を指定すれば、生のAPIレスポンスを `results/openai-provenance.jsonl` に出力する。

```sh
export OPENAI_API_KEY="sk-..."
uv run python scripts/measure_openai_provenance.py \
  --ledger /tmp/detecter-issue65-target-ledger.jsonl \
  --output results/openai-provenance.jsonl \
  --sleep 0.5
```

台帳は既存の `detecter.ufd_batch.load_inputs` スキームに従う：`image_id` / `sha256` / `path` が必須、`generator` / `history` / `condition` があれば集計に使われる。`history` が空なら `original`、resize 1024 + jpeg quality 75 なら `sns-q75`、他の `name` フィールドがあればそれを加工条件名として扱う。

## 5. 成果物

- `src/detecter/openai_provenance.py`
- `scripts/measure_openai_provenance.py`
- `tests/test_openai_provenance.py`
- `results/openai-provenance-smoke.jsonl`（ローカルC2PA smokeの生データ）
- `results/openai-provenance-smoke.summary.json`（上記テーブルの元データ）

## 6. 結論

- OpenAI Content Provenance APIを叩く実装は完成し、429対応のリトライ・生JSONL出力・集計テーブル生成まで動作する。
- APIキーがないため、GPT Image 2系58群・SNS加工・So-Fake4拡散・実写の**OpenAI API計測は未実行**で、smokeはローカルC2PAリーダーのみで実施した。
- smokeからはC2PAがSNS加工で失われることを確認した。SynthIDはAPIでないと計測できないため、APIキー設定後のフォローアップが必要。
