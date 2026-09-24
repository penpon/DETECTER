# Issue #56: UFD + CF + CuRe のアンサンブル判定 (2026-09-24)

Issue #52 の同一コホート比較 (`/tmp/detecter-issue52-comparison.jsonl`、220 画像 × 3 検出器、全件 `ok`) を使い、tuning 174 群で OR アンサンブルと線形統合を評価した記録である。単一検出器の上限 (CF 28/91 群) を統合で上回れるかが問いである。

## 結合方法

純 Python で `image_id` 突合せにより 1 画像ごとに 3 検出器の `raw_score` を結合した。台帳は `/tmp/detecter-issue50-ledger.jsonl` (tuning 174: 実写 83・生成 91、evaluation 46: 実写 22・生成 24) を用いた。群単位の判定規則は較正と同一 (実写=群内最大、生成=群内最小) だが、本コホートは 1 群 1 画像 (220 群/220 画像) のため群判定は画像判定と一致する。

しきい値は各検出器の較正 decision-config の exact 値を `>=` 比較で用いた (docs の丸め値では再現が 1 件ずれるため注意):

- CF: `-0.1506439596414566` (logit、`detecter-issue52-cf-decision-config.json`)
- CuRe: `0.988158643245697` (`detecter-issue52-cure-decision-config.json`)
- UFD: `0.9914475679397584` (`detecter-issue50-decision-config.json`、全体最大の `nextafter`)

丸め値 (`-0.1506` / `0.9882` / `0.9914`) で厳密 `>` 比較すると CF 27・CuRe 12 になり、較正記録 (28・13) と一致しない。較正 (`calibration.py`) の `comparison: ">="` と exact しきい値の併用が再現条件である。

## OR アンサンブル (いずれか 1 検出器が超過なら陽性)

tuning (誤検知 0 のまま評価):

| 対象 | 実写誤検知 | 生成検出 | GPT Image 2 | Nano Banana |
| --- | --- | --- | --- | --- |
| OR (3 検出器) | 0/83 群 | 38/91 群 (41.8%) | 9/45 群 (20.0%) | 29/46 群 (63.0%) |
| CF 単体 | 0/83 群 | 28/91 群 (30.8%) | 5/45 群 | 23/46 群 |
| CuRe 単体 | 0/83 群 | 13/91 群 (14.3%) | 5/45 群 | 8/46 群 |
| UFD 単体 | 0/83 群 | 0/91 群 | 0/45 群 | 0/46 群 |

- OR の内訳: CF のみ 25 群、CuRe のみ 10 群、両方 3 群 (UFD は一度も発火しない)。CF に対する上積み +10 群の内訳は GPT 4 群・NB 6 群である。
- 各しきい値は自検出器の実写最大を上回るため、OR でも tuning 誤検知は 0/83 群に収まる (exact 値 + `>=` の場合のみ。丸め値では 1 件ずれる)。
- UFD は OR に寄与しない (全群でしきい値未満)。実質は CF+CuRe の OR である。

## 線形統合 (min-max 正規化 + 重み付き平均)

各スコアを tuning の min-max で `[0, 1]` に正規化し、重み付き平均の融合スコアについて較正と同じ方針 (誤検知 0 の範囲で検出最大、同数は高いしきい値を選択) で動作点を探した。CF は logit のまま正規化する `raw` 系と、先に安定 sigmoid を適用する `sig` 系の両方を試した。

| 融合 | tuning 動作点 | tuning 生成検出 | GPT / NB | 備考 |
| --- | --- | --- | --- | --- |
| 平均 3 検出器 (raw) | 0.4720 | 26/91 (28.6%) | 7/45・19/46 | UFD 混入で CF 単体を下回る |
| 平均 3 検出器 (sig) | 0.3877 | 20/91 (22.0%) | 5/45・15/46 | 同上 |
| 平均 CF+CuRe (raw 1:1) | 0.6780 | 29/91 (31.9%) | 7/45・22/46 | CF 単体と同等 |
| 平均 CF+CuRe (sig 1:1) | 0.4955 | 34/91 (37.4%) | 7/45・27/46 | OR (38) に届かず |
| CF:CuRe = 2:1 (sig) | 0.3304 | 43/91 (47.3%) | 9/45・34/46 | 最良だが下記注意 |
| CF:CuRe = 1.5:1 (sig) | 0.3964 | 39/91 (42.9%) | 7/45・32/46 | 2:1 の隣接重み |
| CF:CuRe = 3:1 (sig) | 0.2853 | 34/91 (37.4%) | 8/45・26/46 | 重みに敏感 |
| 正規化 max (CFsig, CuRe) | 0.9882 | 19/91 (20.9%) | 6/45・13/46 | OR の代替にならない |

- 重み掃引 (CF:CuRe = 3:1・2:1・1.5:1・1:1・0.75:1・0.5:1・0.25:1、いずれも sig・UFD 除外) では 2:1 の 43/91 が突出し、隣接重みは 34〜39/91 に戻る。2:1 の最良値は tuning 上のしきい値位置合わせによる上振れ (過適合) の可能性が高く、そのまま採用できない。
- 安定して OR を上回る線形重みは見つからなかった。無難な 1:1 平均 (34/91) は OR (38/91) を下回る。
- UFD を含む平均・正規化 max はいずれも CF 単体以下であり、UFD は線形統合でもノイズになる。UFD の実写平均が生成を上回る転倒構造 (#52) が原因である。
- ロジスティック回帰は別途実装していない (sklearn・pandas なし環境のため純 Python の重み掃引で代替)。上記の掃引が線形統合の上限の目安になる。

## evaluation 群への参考適用 (正式な検出率ではない)

tuning で決めた動作点を evaluation 群に機械適用した情報値である。較正 `unmet` のため正式採用の条件を満たさない。

| 方式 | 実写誤検知 (22 群) | 生成検出 (24 群) | GPT 13 群 / NB 11 群 |
| --- | --- | --- | --- |
| OR | 2 群 (`real-1054`, `real-1055`) | 7 群 (29.2%) | GPT 1・NB 6 (CF 単体に対する上積みは `gen-gpt2-0051` の 1 群) |
| 平均 CF+CuRe 1:1 (sig) | 2 群 | 7 群 | GPT 1・NB 6 |
| CF:CuRe 2:1 (sig) | 2 群 | 9 群 | GPT 1・NB 8 |
| CuRe 単体 | 0 群 | 1 群 | GPT 1・NB 0 |
| CF 単体 (#52) | 2 群 | 6 群 | GPT 0・NB 6 |

- いずれの統合も tuning 誤検知 0 を evaluation に汎化できず、CF 単体と同じ 2 群の誤検知が出る。実写 83 群での FP0 保証は弱く、別 issue の実写増強課題と同一である。
- 2:1 重みの tuning 上の優位 (43 vs 38) は evaluation では 9 vs 7 に縮小する。過適合の傍証であり、重み調整での改善主張はできない。

## 結論

- 統合は効くが、目標には遠い。OR で tuning 28/91 → 38/91 群 (+10、41.8%)、NB は 23/46 → 29/46 群 (63.0%) に伸びる。ただし GPT Image 2 は 5/45 → 9/45 群 (20.0%) にとどまり、目標 (誤検知 0.1% 以下かつ検出 90% 以上) には OR・線形統合のいずれも届かない。較正 status は `unmet` のままである。
- 線形統合に OR を超える安定した効果はない。1:1 平均は 34/91 で OR を下回り、2:1 の 43/91 は重み掃引の中で突出した上振れであり evaluation で再現しない。UFD は OR・平均のいずれでも寄与しない (CF+CuRe の問題に帰着する)。
- よって detecter 側の本格実装 (新モジュール・設定拡張) は見送り、最小実装の検討に留めるのが妥当である。

## 最小実装の検討 (実装は行わない)

効いたのが CF+CuRe の OR であるため、実装するなら以下で足りる。新モジュールは不要である。

1. `detecter.comparison` の出力 (または検出器別の `measurements`) を `image_id` で突合せ、各行の `raw_score` に各検出器の較正済み `decision-config` (exact しきい値、`comparison: ">="`) を `apply_decision` 相当で適用する。
2. 画像ごとに陽性判定の OR を取り、群単位に畳み込む (現行 `group_policy: any_positive_real; all_positive_generated` と同一。本コホートは 1 群 1 画像のため自明)。
3. 融合スコア自体の較正 (`calibration.calibrate_records` の流用) は、融合を 1 検出器とみなす場合のみ必要になる。OR 方式では各検出器の較正をそのまま使い、融合後の再較正は不要である。

注意:

- しきい値の丸めは禁止 (exact 値の保存と比較 `>=` が再現条件)。
- UFD を OR に含める実益はない。含める場合は発火なしの旨を記録に残す。
- 融合後の `decision-config` を新設する場合は `status: unmet` になる (38/91 のため)。`validate_config` は `candidate`/`validated` のみを通すため、evaluation 正式適用はできない。参考値の機械適用に留める。
- 線形統合 (正規化 + 重み) を将来試す場合は、min-max の基準範囲 (tuning)・sigmoid の有無・重みを較正条件として記録に含める必要がある。現時点では OR で十分であり、重み付き平均の導入は推奨しない。

## 成果物 (いずれも `/tmp`、リポジトリには含めない)

- `/tmp/detecter-issue52-comparison.jsonl` (入力、660 行)
- `/tmp/detecter-issue50-ledger.jsonl`、`/tmp/detecter-issue50-tuning-ledger.jsonl` (入力)
- `/tmp/detecter-issue52-cf-decision-config.json`、`...-cure-...`、`/tmp/detecter-issue50-decision-config.json` (exact しきい値の取得元)

本 issue ではリポジトリの変更は本ドキュメントのみであり、コード変更・新規ファイル (symlink 類を含む) はない。

## 再現手順

```sh
python3 - <<'PY'
import json, math
from bisect import bisect_left
ledger = {json.loads(l)['image_id']: json.loads(l) for l in open('/tmp/detecter-issue50-ledger.jsonl')}
comp = [json.loads(l) for l in open('/tmp/detecter-issue52-comparison.jsonl')]
joined = {}
for r in comp:
    joined.setdefault(r['image_id'], {})[r['model']] = r['raw_score']
TH_CF = json.load(open('/tmp/detecter-issue52-cf-decision-config.json'))['threshold']
TH_CU = json.load(open('/tmp/detecter-issue52-cure-decision-config.json'))['threshold']
TH_UF = json.load(open('/tmp/detecter-issue50-decision-config.json'))['threshold']
tuning = [i for i in joined if ledger[i]['split'] == 'tuning']
fp = sum(1 for i in tuning if ledger[i]['label'] == 'real' and (joined[i]['community-forensics-384'] >= TH_CF or joined[i]['cure'] >= TH_CU or joined[i]['ufd'] >= TH_UF))
det = sum(1 for i in tuning if ledger[i]['label'] == 'generated' and (joined[i]['community-forensics-384'] >= TH_CF or joined[i]['cure'] >= TH_CU or joined[i]['ufd'] >= TH_UF))
print(fp, det)  # 期待: 0 38
PY
```

線形統合の数値は本ドキュメント「線形統合」節の正規化・重み・選択方針どおりに純 Python で再計算できる (pandas/sklearn 不要)。
