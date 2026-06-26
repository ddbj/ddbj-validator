"""`-b/--biosample`（BioSample 更新用 SSUB TSV 生成）関連を集約したサブパッケージ。

- tsv.py  : SSUB TSV の組み立て（列順・パッケージキー解決・ヘッダ・行生成）
- sync.py : ann↔BioSample 同期の autofix 提案生成（organism/strain/locus_tag_prefix/bioproject_id）
- emit.py : ann→bs 上書き（clean SAMD 判定・override 算出）の純粋ヘルパ

DB からの SSUB 取得は apps/ddbj/db_meta_biosample.py:fetch_biosample_ssub にある
（他の BioSample DB 取得関数と同居しているため当面そちらに残す）。
"""
