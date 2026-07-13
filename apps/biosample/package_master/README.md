# BioSample パッケージ マスター → attributes_packages.json 生成（g sheet のみ）

現行 ruby validator は「3 表 → RDF(TTL) → Virtuoso → SPARQL」で BioSample のパッケージ定義を配信し、
登録システム D-way へ登録用 TSV（パッケージ毎の必須属性に `*`）を返している。
ここでは **Virtuoso を介さず、g sheet のみ**（下記 4 表）から直接 `attributes_packages.json` を生成する。

## 入力（このディレクトリ・固定ファイル名。Google Sheets の各タブの TSV エクスポート）

いずれもタブ区切り（TSV）。タブ・改行・引用符を含むセルは CSV 同様に `"` で quoting される。

Google Sheets（`1myigsvkiftZ2ReqBAll4n3zajwHfyJfccDZNwlcqNak`）の 4 タブ。履歴を残すためリポジトリにコミットする。

| ファイル | タブ | 内容 |
|---|---|---|
| `package.txt` | package | パッケージ定義（Package name / Version / DisplayName / EnvPackage / Group …） |
| `package-attribute.txt` | package-attribute | パッケージ × 属性の use マトリクス（`M`/`O`/`-`/`E:<group>`/`:N`） |
| `attribute-added.txt` | attribute | 属性定義。カラム順 = `Name` `Harmonized name` `Synonym` `type` `allowed_values` `invalid_values` `allow_multiple` `Description` `DescriptionJa`（**Format 列は廃止**）。※ パッケージ別 M/O/E 列は持たない（use は package-attribute.txt にあるため不要） |
| `package-tsv.txt` | package-tsv | パッケージ毎の登録 TSV ヘッダー順（`full_name` + 属性名の並び）。**列順の定義** |

以前は 3 表に無い情報（属性の検証メタ・列順）を `attribute-enrich.json` / `column-order.json` に
リバース抽出していたが、それらを **g sheet に畳み込んだ**（`attribute-added.txt` の追加列 ／ `package-tsv.txt`）。
これにより JSON は g sheet のみから生成できる。

## 実行

```bash
python build_attributes_packages_json.py
# → このディレクトリに attributes_packages.json を出力（apps/biosample/resources/ は上書きしない）
```

生成物は `apps/biosample/resources/attributes_packages.json` と **バイトレベルで完全一致**する（キー順・整形まで一致。全 228 パッケージ検証済み）。
検証: `diff attributes_packages.json ../resources/attributes_packages.json`（差分なし）。
問題なければ手動で resources/ へ反映する（自動上書きはしない）。

## 定義ルール

- **use**（package-attribute.txt）: `M`=mandatory / `O`=optional / `-`=非該当 /
  `E:<group>`=either_one_mandatory（`group` を付与）/ 末尾 `:N`=null 非推奨（現行 JSON は未使用のため無視）。
- **fixed_attributes**: 先頭 6 属性（sample_name..bioproject_id）。use は全パッケージ恒常。
- **列順**（package-tsv.txt）: `full_name` に続く属性名の並びをそのまま列順に採用
  （＝fixed → 準固定 → 必須α → 選択必須α → 任意α）。必須/任意/択一必須の区別は package-attribute.txt から引く。
- **env_package**: `No environmental package` → `""` に正規化。
- **追加列**（attribute-added.txt）:
  - `allowed_values` / `invalid_values`: JSON 配列文字列（例 `["male", "female"]`）。空欄=無し。
  - `allow_multiple`: `true` / `false`。
  - `type`: `integer` / `timestamp` / `reference` 等。空欄=無し。

## TSV 化

`apps/ddbj/biosample/tsv.py`（`build_header` 等）が JSON の属性定義順をそのまま列順として使う。
アクセッション発行後の TSV は `with_accession=True` で先頭に `biosample_accession` を付す（D-way 全パッケージ共通）。

## CSV の再取得

```bash
ID=1myigsvkiftZ2ReqBAll4n3zajwHfyJfccDZNwlcqNak
curl -fsSL "https://docs.google.com/spreadsheets/d/$ID/export?format=tsv&gid=<package gid>"           -o package.txt
curl -fsSL "https://docs.google.com/spreadsheets/d/$ID/export?format=tsv&gid=631330335"              -o package-attribute.txt
curl -fsSL "https://docs.google.com/spreadsheets/d/$ID/export?format=tsv&gid=<attribute(added) gid>" -o attribute-added.txt
curl -fsSL "https://docs.google.com/spreadsheets/d/$ID/export?format=tsv&gid=<package-tsv gid>"       -o package-tsv.txt
```
