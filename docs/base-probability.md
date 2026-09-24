# 基底AI確率（3モデルのロジスティック統合）

CF384・CuRe・UFDの未較正生スコアを1つのロジットへ重み付けし、
シグモイドで基底AI確率 `P(AI) ∈ [0.0, 1.0]` を返します。
画像やモデルは読み込みません。計測記録の`raw_score`をそのまま渡します。

```python
from detecter.base_probability import calibrated_ai_probability
result = calibrated_ai_probability(cf_score=-5.0, cure_score=0.8, ufd_score=0.65)
result["probability"]  # 0.0〜1.0
```

## 係数とメタデータ

既定の重みは調整用データで実証した CF `+0.5185`、CuRe `+2.7269`、
UFD `-3.0123`、バイアス `+3.5753` です。返り値には係数と
`model_condition`（`model`、`model_version`、`weights_version`、
`preprocessing_version`、`calibration_split`）を保存します。
`weights`・`bias`引数で係数を差し替えられます。

UFD係数が負なのは既知の逆転ノイズ（実写で高スコア化する傾向）を
打ち消す方向です。どのスコアも正しさの確率ではないため、返す確率は
キャリブレーション条件にのみ有効な基底確率です。

## 欠測スコア

`None`のスコアはロジットから除外します（中立の0寄与）。
このとき`partial: true`と`missing_scores`を記録し、
不確実性を下流が区別できるようにします。3つ全て欠測、
または非有限値を渡した場合は`ValueError`です。

## 分離性能

`tests/test_base_probability.py`が調整用に記録した実写10群・
生成10群のスコアで、実写中央値約10%・生成中央値約88%、
AUC 1.0（要求0.92以上）を確認します。写真やGPUは不要です。

```sh
uv run python -m unittest discover -s tests -p test_base_probability.py -v
```
