# patent: 特許（ST.26 由来）の ann + FASTA の検査

次期 DDBJ（TSM）の特許の取り込み用。JPO から届く ST.26 の XML を変換した ann + FASTA を検査する。
特許は出願に添付された配列情報をそのまま FF にするので、**FF が作れれば ok** の緩い検査にしている。

```
ddbj-validator patent <dir または ann / fasta> [-o <out>] [-j N] [--json] [-l]
```

- 値に手を入れない（前後の空白・引用符・連続する空白をそのまま読む）。`fixed/` は出さない。出すのは `reports/` だけ。
- 1 set = ann 1 つ + FASTA 1 つ。NA か AA かはファイル名の `_na` / `_aa` で決める。
- `-l` は内部 DB（Taxonomy）を引かない。PAT0043 が動かない。
- `-j` は並列数（既定は最大 8、`0` で全コア）。JSON は `--json`。
- HTTP（`apps/webapi`）には登録していない。CLI だけ。

## 重さ
| 重さ | 意味 |
|---|---|
| error | FF が作れない / 壊れる。error が 1 つでもある set は load しない |
| warning | 人が見る |
| flag | 通して印を返す（accession を振って公開するが INSDC には交換しない、の判断に使う） |
| info | 参考 |

`--json` の `messages` は 1 件が `{id, level, file, entry, …}`。`file` は ann のファイル名（set の名前）。
`stats.flag` に flag の件数が入る。`validity` は error が無いこと。

## ddbj から借りる検査
使う検査を選んでいる（`constants.BORROWED_RULE_IDS`）。前処理・parser・借りた規則が出すそれ以外の id は捨てる。
借りた検査の FATAL は error にそろえる。

| id | 何 |
|---|---|
| ANN0010 / ANN0020 | ann と FASTA の組 |
| ANN0040 | 非 ASCII の文字 |
| ANN0050 | 長すぎる行 |
| SEQ0080 / SEQ0110 / ANN0120 | FASTA の見出し、entry 名の重複 |
| ANN0140 / ANN0190 | 列の数、qualifier 名の欠け |
| ANN0160 | entry 名 |
| AXS0060 / AXS0070 | ann と FASTA の entry の数と名前の対応 |
| ANN2010 / ANN2020 / ANN2030 | source の location の有無と構文 |
| AXS2080 | source の location が配列の長さを超える |
| SEQ5050 | 2.14 Gb を超える |

## 特許の規則
番号は ST.26 の CLI（`PAT_R0008` など）を引き継ぐ。運用の番号と、XML → ann の変換の側で済ませるものは欠番。

| id | 重さ | 何 |
|---|---|---|
| PAT0008 | error | COMMENT の PF の日付が `DD-MON-YYYY` の実在の日でない（`NOT_PROVIDED` は可） |
| PAT0009 | error | PD・PF の日付が 1980-01-01 より前か、今日より後 |
| PAT0010 | error | PD（公開日）が PF（出願日）より前 |
| PAT0011 | error | 1 entry に source が 2 つ以上、または無い |
| PAT0012 | error | KEYWORD の公報番号の形が違う（`<庁> <番号>-<種別>/<配列番号>`） |
| PAT0019 | error | NA の set で source に mol_type が無い。AA の set で mol_type がある |
| PAT0020 | flag | NA の配列に IUPAC の塩基以外の文字 |
| PAT0021 | error | 配列が空 |
| PAT0022 | flag | NA が n だけ |
| PAT0023 | flag | AA が X だけ |
| PAT0024 | error | source の location が `1..<配列の長さ>` でない |
| PAT0028 | error | COMMENT の PD の日付が読めない、または PD 行が無い |
| PAT0030 | error | COMMENT の PR の日付が読めない（PR 行は無くてよい） |
| PAT0031 | error | COMMON の DIVISION が `PAT` でない |
| PAT0032 | error | KEYWORD、REFERENCE（title・journal）、COMMENT、source（organism・ff_definition）のどれかが無い |
| PAT0033 | error | REFERENCE の最初の journal が `Patent: <庁> <番号>-<種別> <配列番号> DD-MON-YYYY;` でない |
| PAT0034 | error | COMMENT に必須の行（OS PN PD PS FH）が無い。行の頭がタグ 2 文字 + 空白 3 つでない |
| PAT0035 | error | entry の中で公報番号と配列番号が食い違う（KEYWORD、ff_definition、journal、PN、PS、entry 名） |
| PAT0036 | error | COMMENT の line と journal が 68 文字を超える |
| PAT0037 | error | AA の配列にアミノ酸の 1 文字以外の文字（ddbj の定義の code。J を含む。`*` は不可） |
| PAT0038 | warning | 短い配列（NA 10 未満、AA 4 未満） |
| PAT0039 | flag | NA の配列にアミノ酸だけの文字（`EFIJLOPQXZ`）= NAwithAA |
| PAT0040 | flag | AA の配列が塩基らしい（A / C / G / T / U が 9 割以上、長さ 10 以上）= AAwithNA |
| PAT0041 | flag | AA の配列が 3 文字表記（長さの半分以上）= AAwith3L |
| PAT0042 | warning | NA の配列に大文字、AA の配列に小文字 |
| PAT0043 | info | organism が Taxonomy に無い（`unidentified` と `synthetic construct` は可。`-l` では動かない） |
| PAT0044 | error | 特許で使わない feature / qualifier がある（`constants.ALLOWED_COMMON` / `ALLOWED_ENTRY`） |
| PAT0045 | error | ファイル名が `_na` / `_aa` で終わらない |
| PAT9999 | error | 内部エラーでその set を検査できなかった |

閾値（PAT0038 / 0040 / 0041）と文字集合は `constants.py` にまとめてある。

## 作り
| ファイル | 役割 |
|---|---|
| `cli.py` | 引数、組の検出、報告の呼び出し |
| `runner.py` | set ごとのワーカー（前処理 → parser → 規則 → JSONL）と並列、Taxonomy の一括取得 |
| `validator.py` | 規則の登録（ddbj の `Validator` を継いで list だけ差し替え） |
| `rules/` | `structure.py`（ann の形）、`sequence.py`（配列。FASTA を 1 回なめる）、`fields.py`（項目の取り出し） |
| `reporter.py` | ddbj の reporter にレベル `FLAG` を足したもの |
| `constants.py` | 閾値・文字集合・使う rule id |

ddbj と共用: 前処理（`preprocess_files(cleanup=False)`）、parser、規則を回す loop、報告。

## test
```
.venv/bin/python apps/patent/tests/run_tests.py            # E2E（内部 DB 不要）
.venv/bin/python apps/patent/tests/run_tests.py PAT0035    # ディレクトリ名で絞る
.venv/bin/python -m pytest tests/unit/test_patent.py       # PAT0043 など E2E で見にくいもの
```
`tests/<規則>/` に ann + FASTA の組を置く。`*.fail_na.ann` / `*.fail_aa.ann` はそのディレクトリ名の id が出ること、
`*.pass_na.ann` / `*.pass_aa.ann` は何も出ないこと。
