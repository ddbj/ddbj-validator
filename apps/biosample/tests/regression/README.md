# BioSample 実データ回帰スイート

本番(Ruby) validator の `result.json` を基準に、現行 Python 版 biosample v の**退行を検知**する
opt-in の回帰テスト。過去 UUID との単純一致率比較（ルール変更に追随できない）を置き換える仕組み。

## 構成
- `manifest.json` … 対象 package の一覧（ssub / package / account / compare.txt / prod_result.json）。
- `<SSUB>/compare.txt` … 網羅ケースを流し込んだ比較用 TSV（`tools/gen_compare.py` で生成）。
- `<SSUB>/prod_result.json` … 管理システムで validate only した本番の結果（基準）。
- `known_diffs.json` … 本番と**意図的に異なる**差分の基準（詳細 `docs/biosample/known-differences.md`）。
- `run_regression.py` … 現行 v を実行し本番と sample×rule 突合、known_diffs 以外の差分を検出。

## 実行（要内部DB。既定 E2E / make push には含めない）
```bash
python apps/biosample/tests/regression/run_regression.py            # 検証（既知差分のみなら PASS）
python apps/biosample/tests/regression/run_regression.py SSUB047754 # 単一 package
python apps/biosample/tests/regression/run_regression.py --update   # 基準(known_diffs.json)を現状で更新
```

## 新パッケージの追加手順
1. 本番にテスト SSUB を登録し、`tools/gen_compare.py` に package config を足して compare.txt を生成
   （clean control が無反応になるよう baseline は必須/either_one を満たすこと）。
2. 管理システムで validate only → UUID の result.json を取得。
3. `<SSUB>/compare.txt` と `<SSUB>/prod_result.json` を置き、`manifest.json` に追記。
4. `run_regression.py --update` で known_diffs.json に基準を追加。差分は known-differences.md にも反映。

## 注意
- compare.txt / prod_result.json は dradev のテスト登録に紐づく実データ。テスト SSUB の内容を変更したら
  本番 result.json を取り直して基準を更新すること。
