# 評価コホートの作成

`detecter.cohort` はローカルの画像を検証して評価台帳を作り、Issue #30 の充足状況を報告します。
画像本体はリポジトリへ入れず、評価端末上の保管場所だけを記録します。

## 手順

```sh
uv run python -m detecter.cohort scan /path/to/photos \
  --output inventory.jsonl --limit 4000
uv run python -m detecter.cohort build \
  --manifest cohort.json --ledger ledger.jsonl --seed 20260923 \
  --evaluation-fraction 0.87 --report build.json
uv run python -m detecter.cohort report \
  --ledger ledger.jsonl --manifest cohort.json --report coverage.json
```

`scan` はディレクトリ内の画像を読み、SHA-256、形式、寸法、撮影機器（EXIFのMake/Model）を
目録へ記録します。撮影機器を確認できない画像は既定で除外します。`--allow-missing-camera`で
全画像を記録できます。`--threads`は並列に読み込むファイル数で、ネットワーク上の保管場所では
既定値のままで構いません。`--limit`は記録する件数の上限です。
`--suffixes .heic,.heif`のように拡張子を絞ると、形式ごとの件数を揃えられます。

`build` はマニフェストの各出所について目録を読み、台帳の行を作ります。
`--seed`を指定すると、分割先を固定していない出所だけを元画像グループ単位で
`tuning`と`evaluation`へ分割します（[評価画像の台帳](ledger.md)と同じ順位付け）。
分割先を固定した出所はそのまま残します。

`report` は台帳を読み直し、充足状況をJSONで出力します。既定では画像のSHA-256を
再計算しません。全画像を確認する場合は`--verify-files`を指定するか、
`uv run python -m detecter.ledger validate <台帳>`を実行します。画像パスは絶対パスで、
`--repository-root`の下にある画像があれば`outside_repository`を不足として報告します。

## マニフェスト

```json
{
  "sources": [
    {
      "root": "/Volumes/Multimedia/iphone",
      "inventory": "ledger/real-inventory.jsonl",
      "label": "real",
      "source": "所有者による撮影",
      "license": "評価利用のみ・再配布しない",
      "id_prefix": "real",
      "camera": null
    },
    {
      "root": "/Users/nana/workspace/detecter-cohort/generated/gpt-image-2.5",
      "inventory": "ledger/gpt-image-2.5.jsonl",
      "label": "generated",
      "generator": "GPT Image 2.5",
      "generator_model": "gpt_image_2_5",
      "provenance": "/Users/nana/workspace/detecter-cohort/receipts",
      "source": "higgsfield:gpt_image_2_5",
      "license": "自己生成・評価利用可",
      "id_prefix": "gen-gpt25",
      "split": "evaluation"
    }
  ],
  "requirements": {
    "minimum_real_groups": 3000,
    "minimum_edited_groups": 10,
    "required_generators": {"GPT Image 2.5": 29, "Nano Banana Pro": 29},
    "out_of_scope": ["Midjourney"]
  }
}
```

元画像グループは、同じ写真を別形式や別品質で保存した複製を分割しないよう、
目録の知覚ハッシュ（64ビットのdHash）でまとめます。同じ写真が調整用と最終評価用へ
分かれる漏洩を防ぐため、分割は元画像グループ単位で行います。

`label`は`real`、`generated`、`edited`です。`real`はEXIFの撮影機器が必須で、
`camera`に`Make Model`を記録します。`generated`と`edited`は`generator`が必須で、
`edited`は加工履歴（`history`）も必須です。`provenance`を指定すると、
生成ジョブの記録ファイルを`<provenance>/<画像名>.json`として行へ残します。

## 充足状況

`report`の`checks`が受け入れ条件ごとの結果です。

| id | 内容 |
| --- | --- |
| `real_source_groups` | 最終評価の実写元画像グループ数が`minimum_real_groups`以上 |
| `generator_groups` | 必須生成器群が`required_generators`の最小数を満たす（Issue #27と同じ集計） |
| `camera_diversity` | 実写が複数の撮影機器を含む |
| `heif_inputs` | HEIF/HEIC入力が台帳にある |
| `split_holdout` | 調整に使わない生成器版が最終評価に残っている |
| `derived_condition_parity` | 加工版の条件が実写と生成画像の両方にある |
| `edited_groups` | 部分編集の元画像グループ数が`minimum_edited_groups`以上 |
| `outside_repository` | 画像がリポジトリの外にある |

`generator_groups`の状態は`met`、`below_minimum`、`insufficient_data`です。
不足した群は達成として扱わず、`--required-generator NAME:COUNT`へ渡して
`detecter evaluate-pipeline`でも同じ判定を再現できます。

## ローカルの保管場所と利用条件

この評価で使う画像はリポジトリへ追加しません。

- 実写は所有者が撮影した個人写真で、`/Volumes/Multimedia/iphone`へ保管しています。
  再配布せず、評価端末からのみ読み取ります。写真の写り込みへ配慮し、台帳には
  画像パスとSHA-256だけを記録します。
- 生成画像はHiggsfield経由で自分のアカウントで生成し、
  `/Users/nana/workspace/detecter-cohort/generated`へ保管しています。
  生成時のプロンプト、モデル、パラメータ、ジョブIDは
  `/Users/nana/workspace/detecter-cohort/receipts`へ残しています。
- 加工版は`/Users/nana/workspace/detecter-cohort/derived`へ生成し、
  元画像と同じ元画像グループ・分割先で台帳へ登録します。
- Midjourneyは今回の評価対象外とします（対象範囲の不足として記録）。

## 現在のローカルコホート

次の結果は`/Users/nana/workspace/detecter-cohort/coverage.json`の`checks`と一致します。

| 対象 | 件数 | 分割 |
| --- | --- | --- |
| 実写（`/Volumes/Multimedia/iphone`） | 5,895件 | 最終評価5,085件・3,752元画像グループ、調整810件・625元画像グループ |
| GPT Image 2.5（評価専用） | 29件 | 最終評価 |
| Nano Banana Pro（評価専用） | 29件 | 最終評価 |
| GPT Image 2（調整専用） | 12件 | 調整 |
| Nano Banana 2 Lite（調整専用） | 12件 | 調整 |
| Nano Banana Proによる部分編集 | 18件 | 最終評価 |
| JPEG品質と縮小の加工版 | 200件（実写20＋生成20に5条件） | 元画像と同じ分割 |

撮影機器は14種類（iPhone XS、iPhone 11 Pro、iPhone 13、SONY ILCE-7M3、
Canon EOS R3など）、入力形式はJPEG 5,387件、HEIF 508件、PNG 200件です。
同じ写真を別形式・別品質で保存した複製は知覚ハッシュで1グループへまとめるため、
元画像グループ数はファイル数より少なくなります。
台帳は`/Users/nana/workspace/detecter-cohort/ledger/cohort-final-ledger.jsonl`に置き、
`detecter.ledger validate`で画像ハッシュを再確認できます。
Midjourneyは対象外のため、`requirements.out_of_scope`へ記録しています。
