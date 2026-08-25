# DDBJ Validator

DDBJ Validator は、DDBJ (DNA Data Bank of Japan) に登録するアノテーションファイル（`.ann`）と塩基配列 FASTA ファイル（`.fasta`）の構文や整合性を検証・自動修正するためのコマンドラインツールです。

本ツールはローカルでのフォーマットチェックに加え、NCBI Taxonomy API と連携し、登録前の詳細なバリデーション（Taxonomy に依存した整合性確認など）を行うことができます。

DDBJ の既存チェックツールである [jParser](https://www.ddbj.nig.ac.jp/ddbj/parser.html) による構文チェック、[transChecker](https://www.ddbj.nig.ac.jp/ddbj/transchecker.html) による CDS アミノ酸翻訳機能に加え、Taxonomy に依存した確認や [INSDC Minimal Specifications](https://www.insdc.org/insdc-minimal-specifications/) で定められた要件を検証する機能を提供しています。

## ベータ版リリース

2026年5月18日、本ツールをベータ版としてリリースいたしました。  
いずれは正式版の公開を目指して開発を進めておりますが、現在は初期段階であり、一部に不具合が含まれている可能性がございます。今後の品質向上のため、広くユーザの皆様からのフィードバックを募集しております。  
不具合の報告や改善のご要望などは [GitHub Issues](https://github.com/ddbj/ddbj-validator/issues) や [DDBJ Validator フォーム](https://docs.google.com/forms/d/e/1FAIpQLSeNybDSYLbS3oMHruheAtaXQOArsT_s7ezjJr-Q5r_YWENZIA/viewform?usp=header)よりお寄せください。

## ルールリスト

現在適用されているバリデーションルールの詳細については、スプレッドシート [Validation rules](https://docs.google.com/spreadsheets/d/1Bb4yG0UeC5Y-oem7cMZFHhL1PtvuXG73tqQs5_tr-sw/edit?gid=0#gid=0)を参照してください。

## Docker を使った方法

### インストール

本ツールを実行するには、Docker がインストールされている必要があります。

* Windows/macOS: [Docker Desktop](https://www.docker.com/products/docker-desktop/) をインストールしてください。
* Linux: [Docker Engine](https://docs.docker.com/engine/install/) をインストールしてください。

以下のコマンドで最新のイメージを取得します。

```bash
docker pull ghcr.io/ddbj/ddbj-validator:latest

```

### 使い方

#### A. ラッパースクリプトを使用する（推奨）

リポジトリに含まれるスクリプトを使用すると、複雑な Docker コマンドを入力せずに実行できます。

**macOS/Linux (Unix 系)** `ddbj-validator-seq.sh` があるディレクトリで実行します。

```bash
# 実行権限を付与（初回のみ）
chmod +x ddbj-validator-seq.sh

# 実行（カレントディレクトリのファイルを検証）
./ddbj-validator-seq.sh [オプション] [検証対象ディレクトリ]

```

対象ディレクトリを省略した場合、カレントディレクトリが対象となります。

**Windows** コマンドプロンプトまたは PowerShell で `ddbj-validator-seq.bat` を実行します。

```bash
ddbj-validator-seq.bat [オプション] [検証対象ディレクトリ]

```

#### B. Docker コマンドを直接実行する

直接 `docker run` で実行する場合の基本構造は以下の通りです。カレントディレクトリをコンテナの /data にマウントし、そこを作業ディレクトリとして実行します。不正フォーマットなどの自動修正（Autofix）を行う際、対話式でキーボード入力を受け付けるために `-it` オプションを指定します。

```bash
# macOS/Linux
docker run -it --rm -v $(pwd):/data -w /data ghcr.io/ddbj/ddbj-validator:latest [オプション] target_directory

# Windows (PowerShell)
docker run -it --rm -v "${PWD}:/data" -w /data ghcr.io/ddbj/ddbj-validator:latest [オプション] target_directory

```

## pip を使った方法

システムの Python 環境への影響を避けるため、仮想環境（`venv` など）の利用を推奨します。（前提条件: Python 3.x, Git）

### インストール

1. リポジトリをクローンし、プロジェクトのディレクトリに移動します。

```bash
git clone https://github.com/ddbj/ddbj-validator
cd ddbj-validator

```

2. Pythonの仮想環境を作成し、アクティベートします。

```bash
# macOS/Linux (Unix 系)
python -m venv .venv
source .venv/bin/activate

# Windows (コマンドプロンプト/PowerShell)
python -m venv .venv
.venv\Scripts\activate

```

3. `pip` を使用してパッケージをインストールします。

```bash
pip install .

```

### 使い方

インストール後は、専用のコマンドラインツールとして実行できます。
仮想環境がアクティベートされている状態（コマンドプロンプトの先頭に (.venv) などが表示されている状態）であれば、直接 ddbj-validator コマンドを使用できます。

```bash
# 基本的な実行（対象ディレクトリ内のファイルを検証）
ddbj-validator [オプション] [検証対象ディレクトリ]

```

仮想環境をアクティベートしていない状態から実行する場合は、実行ファイルのパスを直接指定してください。

```bash
# 仮想環境をアクティベートしていない場合 (macOS/Linux の例)
.venv/bin/ddbj-validator [オプション] [検証対象ディレクトリ]

```

## 主要なコマンドラインオプション

* `-o`, `--out-dir` レポート結果（Summary, Details）や自動修正済みファイルの出力先ディレクトリを指定します。
* `-n`, `--ncbi-api` (推奨) NCBI API を利用して Taxonomy の検証を行います。DDBJ のデータベースへの接続はスキップされます。
* `-l`, `--local` 完全にローカルな環境で動作します。DB および API へのアクセスをスキップし、ファイルのチェックのみを行います。
* `-f`, `--force-fix` フォーマットエラーや修正事項（Autofix）が見つかった際、対話プロンプトでの確認をスキップしてすべて自動適用します。
* `-j`, `--jobs` 並列処理するプロセス数を指定します。指定しない場合は環境に合わせて自動設定されます（最大8）。`0` を指定すると、利用可能なすべての CPU コアを使用します。
* `--ncbi-api-key` NCBI API へのリクエスト制限を緩和するための API キーを指定します。
* `--help` 利用可能なすべてのオプションと詳細を確認します。

#### 実行例

NCBI API（`-n`）を利用し、結果を output（`-o`）フォルダに出力し、並列数4（`-j 4`）で実行する場合：

**Docker (ラッパースクリプト) の場合:**

```bash
./ddbj-validator-seq.sh -n -o output_directory -j 4 target_directory

```

**pip (直接コマンド実行) の場合:**

```bash
ddbj-validator -n -o output_directory -j 4 target_directory

```

### NCBI API の設定（推奨）

`-n` オプションで NCBI API（E-utilities）を利用する場合、NCBI の利用ガイドラインに沿って
実行ディレクトリに `.env` を作成し、以下のいずれかを設定することを推奨します（ツールが自動で読み込みます）。

NCBI からの推奨は「**API キーが望ましい。無ければ最低限メールアドレス**」です。

```ini
# 推奨: API キー（NCBI アカウントで取得。レート制限が 3→10 req/s に緩和され、利用がアカウントに紐づく）
NCBI_API_KEY=あなたの_NCBI_API_KEY文字列

# API キーが無い場合は、連絡先メールアドレスの設定を推奨
#（過剰アクセス時に NCBI から事前連絡を受けられ、予告なしのブロックを避けやすい）
NCBI_API_EMAIL=あなたのメールアドレス
```

- **API キーも メールアドレスも未設定**でも動作しますが、レート制限は 3 req/s（IP 単位）で、
  超過時に一時ブロックされる可能性があります。頻繁に利用する場合は `NCBI_API_KEY` の取得を推奨します。
- API キーは [こちら](https://www.ncbi.nlm.nih.gov/books/NBK25497/#chapter2.Usage_Guidelines_and_Requiremen#chapter2.API_Keys)から取得できます。

## メモリ使用量

本ツールは並列数に比例してメモリを消費します。1プロセスあたりのメモリ使用量は、対象となる個別の FASTA ファイルサイズに大きく依存します。メモリ不足（OOM）による強制終了を防ぐため、以下の目安を参考に `-j` の数値を調整してください。

【メモリ消費の目安（実測値）】

* 巨大な配列データ（FASTA が数GBクラス/ヒトゲノム等）
* 1ファイル（約3GB）の処理につき、約15GB〜18GB のメモリを消費します。
* `-j 4` では約55GB、`-j 8` では約100GBのRAMが必要になります。

* 小さな配列データ群（FASTA が数十〜数百MBクラス/TSA や短いアセンブリ等）
* 1ファイル（約100MB）の処理につき、約1.5GB〜2GB のメモリを消費します。
* `-j 8` でも約8GB程度に収まるため、標準的な並列処理が可能です。

## 動作の仕組みと出力結果

ツールを実行すると、指定したディレクトリ内の `*.ann` と `*.fasta` のペアを自動的に検索し、検証を行います。
検証が完了すると、出力ディレクトリ（指定がない場合は対象ファイルと同じディレクトリ）に以下のフォルダ群が生成されます。

* `reports/` 検証結果の各種レポートテキストが格納されます。
    * `validation_report_summary.txt`: エラー（ERROR/FATAL）や警告（WARNING）のサマリー です。ルールごとの発生件数を確認できます。
    * `validation_report_details.txt`: エラーや警告が発生した行番号やメッセージの全リストです。
    * `autofix_confirmation_summary.txt`: Autofix（自動修正）の提案一覧です。
* `fixed/` 承認された Autofix（または、`-f` オプションで自動適用された修正）が反映されたファイルが格納されます。
* `aa/` CDS feature から翻訳されたアミノ酸配列（FASTA 形式）が格納されます。

# 各データベースの検証（サブコマンド）

本ツールは塩基配列アノテーション（`ddbj`）以外にも、DDBJ の各データベースの登録データを
サブコマンドで検証できます。第 1 引数がサブコマンド名でない場合は暗黙的に `ddbj` が補完されるため、
`ddbj` サブコマンドは省略できます（上記「使い方」はこの `ddbj` の説明です）。

| サブコマンド | 対象 | 入力 |
|---|---|---|
| `ddbj`（省略可・既定） | 塩基配列アノテーション | `.ann` ＋ FASTA のペア（ディレクトリ） |
| `bioproject` | BioProject | XML |
| `biosample` | BioSample | XML / TSV / DDBJ Record（v3 JSON） |
| `dra` | DRA（Sequence Read Archive） | Submission/Experiment/Run/Analysis XML |
| `gea` | GEA（Genomic Expression Archive） | MAGE-TAB（IDF/SDRF） |
| `metabobank`（`mb`） | MetaboBank | MAGE-TAB（IDF/SDRF） |

## 共通事項

- **実行モード**（`ddbj` 以外の 5 サブコマンド共通）
  - 既定（フラグ無し）: **NCBI API モード**（内部 DB・権限検証をスキップ、Taxonomy は NCBI API で確認。一般ユーザ向け）
  - `-l`, `--local`: 完全ローカル（DB・API アクセスなし）
  - `-n`, `--ncbi-api`: NCBI API モード（明示。既定と同じ）
  - `-d`, `--internal-db`: 内部 DDBJ DB を使う **curator モード**（権限検証あり）
  - 環境変数 **`DDBJ_VALIDATOR_INTERNAL_DB=1`** で、フラグ無しの既定を curator（内部 DB）モードにできます（`.env` 可）。`-l`/`-n`/`-d` は常に優先。
  - `--account <submitter_id>` は **内部 DB モードでのみ有効**（他モードと併用するとエラー終了）。
- **出力**: `-o`/`--out-dir` 指定先（省略時は入力ファイルの親）に `reports/` を作成し、
  `validation_report_summary.txt` と `validation_report_details.txt` を出力します。
  `-j`/`--json` を付けると代わりに `validation_report.json` を出力します。
  - 注: `-j` の意味はサブコマンドで異なります。**`ddbj` のみ `-j` は並列数**（JSON は `--json`）。
    それ以外（`bioproject`/`biosample`/`dra`/`gea`/`metabobank`）は **`-j`/`--json` が JSON 出力**です。

## BioProject（`bioproject`）

BioProject 登録 XML を検証します。

```bash
# XML を指定（-x は必須）
ddbj-validator bioproject -x PSUB012060.xml
```

- 入力: `-x`, `--xml`（BioProject XML、**必須**）。
- モード: 既定 NCBI API。内部 DB モード（`-d`）では umbrella/locus_tag/重複チェック用のメタ情報を取得します。
- サンプル: `docs/bioproject/PSUB003313.xml` ほか。

## BioSample（`biosample`）

BioSample 登録データ（XML / TSV / DDBJ Record）を検証します。

```bash
# XML 入力
ddbj-validator biosample -x SSUB045342.xml

# TSV 入力（submission id / package はファイル名 SSUBxxxx.<Package>.txt から補完。-s/-p で明示指定可）
ddbj-validator biosample -t SSUB045342.Human.txt [-s SSUB045342] [-p Human]

# DDBJ Record 入力（v3 JSON。record の samples[] を検証する）
ddbj-validator biosample -r SSUB045342.json [-s SSUB045342]
```

- 入力: `-x`, `--xml` / `-t`, `--tsv` / `-r`, `--record`（いずれか 1 つ必須）。TSV は内部で XML に変換して検証します。
- `-s`, `--submission-id` / `-p`, `--package`: TSV の submission id / package。省略時はファイル名（`SSUBxxxx.<Package>.txt`）から補完。
  Record は submission id を持たないため `-s` で渡します（`-p` は Record では使えません。package は
  `samples[].package` から取るため、併用するとエラーになります）。
- autofix は常に自動適用され、修正済みファイルを `fixed/` に出力します。**形式は入力に従います**
  （XML/TSV 入力なら XML、Record 入力なら Record）。`reports/` には autofix 確認ファイルも出力します。
- モード: 既定 NCBI API。`-d` で内部 DB（account / BioProject / 登録済み locus_tag_prefix の取得）。
- サンプル: `docs/biosample/SSUB045342.xml` / `SSUB045342.txt` ほか。

### DDBJ Record（v3 JSON）入力について

[ddbj/ddbj-record-specifications](https://github.com/ddbj/ddbj-record-specifications) の v3 レコードを
そのまま入力にできます。検証ルールは XML/TSV と同じものが同じように動きます（`record_reader` が
XML と同じ内部モデルを組むため、ルールは入力形式を区別しません）。

対応関係と、v3 に無いために呼び出し側から渡す必要があるものは `apps/biosample/record_reader.py`
の docstring にまとめてあります。要点:

- **`samples[]` のみを見ます。** `project` などが同居していても検証しません（BioProject は今後対応）。
  `samples` が無い record は「指摘ゼロ」ではなく入力エラーとして落とします。
- `submission_id` は record が持たないので `-s` で渡します。**省略すると `BS_R0091` が
  そのサブミッション自身の locus_tag_prefix を重複として報告します**（警告を出します）。
  `--account` も同様に record からは取れず、省略すると権限系ルール（`BS_R0006` 等）は動きません。
- 値が typed slot（`organism` / `title` / …）と属性バッグのどちらに載っていても拾います。
  値は XML 入力と同じく全て strip します。
- **`attributes[].unit` は見ていません。** BioSample の XML/TSV に単位の概念が無く、ルールも
  単位を見ないためです。単位付きの値をどう扱うかは未決で、現状は値だけを検証します。
- スキーマ検証（`BS_R0098`）は `ddbj-record` パッケージを使います（`[record]` extra。
  Docker イメージには同梱済み）。入っていない場合でも reader が前提とする形の検査は行い、
  スキーマ検証を行わなかったことを stderr に警告します。
- autofix は typed slot と属性バッグの両方を揃えて書き戻します（片方だけ直すと、
  直したはずの record を再検証したときに同じ指摘が出なくなるため）。

## DRA（`dra`）

1 セッション分の DRA XML 群（Submission / Experiment / Run / Analysis）を検証します。

```bash
# ディレクトリ指定（中の *.xml をルート要素で役割自動判定）
ddbj-validator dra docs/dra/dradev-0062/

# ファイルを個別指定（--ana は任意）
ddbj-validator dra --sub xxx_submission.xml --exp xxx_experiment.xml --run xxx_run.xml [--ana xxx_analysis.xml]
```

- 入力: positional でディレクトリ、または `--sub`/`--exp`/`--run`/`--ana`（各複数指定可）で個別に。両者併用可。
- モード: 既定 NCBI API。`-d` で内部 DB（account・DB 依存ルール用メタ取得）。
- サンプル: `docs/dra/dradev-0062/`（analysis 無し）、`docs/dra/amr_ddbj-0104/`（analysis 有り）。

## GEA（`gea`）

GEA の MAGE-TAB（IDF / SDRF）を検証します。

```bash
# ディレクトリ指定（*.idf.txt / *.sdrf.txt を自動検出）
ddbj-validator gea docs/gea/magetab/E-GEAD-1103/

# ファイルを個別指定
ddbj-validator gea --idf E-GEAD-1103.idf.txt --sdrf E-GEAD-1103.sdrf.txt
```

- 入力: positional でディレクトリ、または `--idf` / `--sdrf`。
- モード: 既定 NCBI API。`-d` で内部 DB（BioSample 属性突合 `GEA_BS0001-0003`、参照先の登録確認 `GEA_REF`）。
- autofix: `-f`, `--force-fix` で全適用、または対話（提案ごとにキー入力）。日付 `/`→`-`、非推奨 null→`missing`、Experimental Factor Type の補完などを `fixed/` に出力。
- **BioSample ↔ SDRF 同期の autofix**（`GEA_BS0003` の値不一致）は双方向:
    - 既定（`[y]` / `-f`）= **BioSample → SDRF**（`fixed/` の SDRF を BS 値へ修正。入力 SDRF は変更しません）。
    - `-b`, `--biosample`（内部 DB 必須）併用時のみ **SDRF → BioSample**（`[b]`）を選べ、`biosample/` に SSUB 単位の BioSample 更新 TSV を出力します。
    - autofix の確認内容は `reports/autofix_confirmation_summary.txt` に出力されます。
- MetaboBank の MAGE-TAB など GEA 以外の入力を検出した場合はエラーで中断します。
- サンプル: `docs/gea/magetab/E-GEAD-1103/` ほか。

## MetaboBank（`metabobank` / `mb`）

MetaboBank の MAGE-TAB（IDF / SDRF）を検証します。`mb` は `metabobank` の別名です。

```bash
# ディレクトリ指定（*.idf.txt / *.sdrf.txt を自動検出）
ddbj-validator mb docs/mb/magatab/MTBKS231/

# ファイルを個別指定
ddbj-validator metabobank --idf MTBKS231.idf.txt --sdrf MTBKS231.sdrf.txt
```

- 入力: positional でディレクトリ、または `--idf` / `--sdrf`。
- モード: 既定 NCBI API。`-d` で内部 DB（BioSample 属性突合 `MB_SR0021-0023`。SDRF の全 Characteristics 属性を BioSample と突合）。
- autofix: `-f`, `--force-fix` で全適用、または対話（提案ごとにキー入力）。日付 `/`→`-`〔MB_IR0013〕、非推奨 null→`missing`〔MB_IR0021〕、Experimental Factor Type の補完〔MB_IR0035〕を `fixed/` に出力。
- **BioSample ↔ SDRF 同期の autofix**（`MB_SR0023` の値不一致。MetaboBank の SDRF は BioSample の引き写しのため双方向）:
    - 既定（`[y]` / `-f`）= **BioSample → SDRF**（`fixed/` の SDRF を BS 値へ修正。入力 SDRF は変更しません）。
    - `-b`, `--biosample`（内部 DB 必須）併用時のみ **SDRF → BioSample**（`[b]`）を選べ、`biosample/` に SSUB 単位の BioSample 更新 TSV を出力します。
    - autofix の確認内容は `reports/autofix_confirmation_summary.txt` に出力されます。
- GEA の MAGE-TAB など MetaboBank 以外の入力を検出した場合はエラーで中断します。
- サンプル: `docs/mb/magatab/MTBKS231/` ほか。

# DDBJ Validator

The DDBJ Validator is a command-line tool to validate and automatically fix the syntax and consistency of annotation files (`.ann`) and nucleotide sequence FASTA files (`.fasta`) for submission to the DDBJ (DNA Data Bank of Japan).

In addition to format validation, this tool uses the NCBI Taxonomy API to perform detailed validation such as taxonomy-dependent checks before submission.

Alongside the syntax validation by DDBJ's existing tool [jParser](https://www.ddbj.nig.ac.jp/ddbj/parser-e.html) and the CDS amino acid translation features of [transChecker](https://www.ddbj.nig.ac.jp/ddbj/transchecker-e.html), this tool provides taxonomy-dependent validations and checks required by the [INSDC Minimal Specifications](https://www.insdc.org/insdc-minimal-specifications/).

## Beta Release

On May 18, 2026, we released the tool as a beta version.  
While we are developing with the goal of an official release in the future, it is currently in its early stages and may contain some bugs. To help us improve the tool, we are actively seeking feedback from our users.   
Please submit bug reports, feature requests, or any other feedback via [GitHub Issues](https://github.com/ddbj/ddbj-validator/issues) or the [DDBJ Validator Form](https://docs.google.com/forms/d/e/1FAIpQLSeNybDSYLbS3oMHruheAtaXQOArsT_s7ezjJr-Q5r_YWENZIA/viewform?usp=header).

## Rule List

For details on the validation rules, please refer to the spreadsheet [Validation rules](https://docs.google.com/spreadsheets/d/1Bb4yG0UeC5Y-oem7cMZFHhL1PtvuXG73tqQs5_tr-sw/edit?gid=0#gid=0).

## Using Docker

### Installation

Docker must be installed to run this tool.

* Windows/macOS: Please install [Docker Desktop](https://www.docker.com/products/docker-desktop/).
* Linux: Please install [Docker Engine](https://docs.docker.com/engine/install/).

Download the latest image using the following command:

```bash
docker pull ghcr.io/ddbj/ddbj-validator:latest

```

### Usage

#### A. Using the Wrapper Script (Recommended)

You can execute the tool without entering complex Docker commands by using the scripts included in the repository.

**macOS/Linux (Unix-like)** Execute the script in the directory where `ddbj-validator-seq.sh` is located.

```bash
# Grant execution permission (first time only)
chmod +x ddbj-validator-seq.sh

# Execute (validates files in the current directory)
./ddbj-validator-seq.sh [Options] [Target Directory]

```

If the target directory is omitted, the current directory will be validated.

**Windows** Execute `ddbj-validator-seq.bat` in the Command Prompt or PowerShell.

```bash
ddbj-validator-seq.bat [Options] [Target Directory]

```

#### B. Running Docker Commands Directly

The basic structure for executing the tool directly via `docker run` is as follows. Mount the directory containing the files you want to validate to `/data` inside the container.

```bash
# macOS/Linux
docker run -it --rm -v $(pwd):/data -w /data ghcr.io/ddbj/ddbj-validator:latest [Options] target_directory

# Windows (PowerShell)
docker run -it --rm -v "${PWD}:/data" -w /data ghcr.io/ddbj/ddbj-validator:latest [Options] target_directory

```

## Using pip

To avoid affecting your system's Python environment, we recommend using a virtual environment (e.g., `venv`). (Prerequisites: Python 3.x, Git)

### Installation

1. Clone the repository and navigate to the project directory.

```bash
git clone https://github.com/ddbj/ddbj-validator
cd ddbj-validator

```

2. Create and activate a Python virtual environment.

```bash
# macOS/Linux (Unix-like)
python -m venv .venv
source .venv/bin/activate

# Windows (Command Prompt/PowerShell)
python -m venv .venv
.venv\Scripts\activate

```

3. Install the package using `pip`.

```bash
pip install .

```

### Usage

After installation, the tool can be run as a command-line tool. 
If your virtual environment is activated (typically indicated by (.venv) at the beginning of your command prompt), you can run the ddbj-validator command directly.

```bash
# Basic execution (validates files in the target directory)
ddbj-validator [Options] [Target Directory]

```

If the virtual environment is not activated, you must specify the direct path to the executable.

```bash
# When the virtual environment is not activated (Example for macOS/Linux)
.venv/bin/ddbj-validator [Options] [Target Directory]

```

## Main Command-Line Options (Common)

* `-o`, `--out-dir`: Specifies the output directory for the report files (summary, details) and auto-fixed files.
* `-n`, `--ncbi-api`: (Recommended) Uses the NCBI API for Taxonomy validation. Skips access to the DDBJ databases.
* `-l`, `--local`: Runs in a completely local environment. Skips access to databases and APIs, performing only file checks.
* `-f`, `--force-fix`: Automatically applies all fixes (Autofix) found, skipping the interactive confirmation prompt.
* `-j`, `--jobs`: Specifies the number of parallel processes. If not specified, it is automatically set according to the environment (maximum of 8). If `0` is specified, all available CPU cores will be used.
* `--ncbi-api-key`: Specifies an API key to ease request limits to the NCBI API.
* `--help`: Displays all available options and details.

#### Execution Example

When using the NCBI API (`-n`), outputting results to an `output_directory` (`-o`), and using 4 parallel processes (`-j 4`):

**For Docker (Wrapper script):**

```bash
./ddbj-validator-seq.sh -n -o output_directory -j 4 target_directory

```

**For pip (Direct command):**

```bash
ddbj-validator -n -o output_directory -j 4 target_directory

```

### Setting up the NCBI API (Recommended)

When using the NCBI API (E-utilities) via the `-n` option, following NCBI's usage guidelines,
create a `.env` file in your working directory and set one of the following (the tool loads it automatically).

NCBI recommends: **an API key is preferred; otherwise, at least an email address.**

```ini
# Recommended: API key (obtained from your NCBI account; relaxes the rate limit 3 -> 10 req/s and ties usage to your account)
NCBI_API_KEY=your_ncbi_api_key_string_here

# If you do not have an API key, setting a contact email is recommended
# (lets NCBI contact you before blocking on excessive use, avoiding sudden blocks).
NCBI_API_EMAIL=your_email_address
```

- It works even with **neither the API key nor the email set**, but the rate limit is 3 req/s (per IP)
  and you may be temporarily blocked when exceeding it. For frequent use, obtaining an `NCBI_API_KEY` is recommended.
- Get an API key [here](https://www.ncbi.nlm.nih.gov/books/NBK25497/#chapter2.Usage_Guidelines_and_Requiremen#chapter2.API_Keys).

## Memory Usage

This tool consumes memory proportional to the number of parallel processes. The memory usage per process is highly dependent on the size of the individual FASTA file being processed. To prevent forced termination due to Out of Memory (OOM) errors, please adjust the `-j` value using the following guidelines.

[Memory Consumption Guidelines (Measured Values)]

* Large sequence data (FASTA files in the gigabyte range/Human genome, etc.)
* Processing 1 file (approx. 3GB) consumes about 15GB to 18GB of memory.
* `-j 4` requires about 55GB, and `-j 8` requires about 100GB of RAM.

* Small sequence data sets (FASTA files in the tens to hundreds of megabytes range/TSA, short assemblies, etc.)
* Processing 1 file (approx. 100MB) consumes about 1.5GB to 2GB of memory.
* Even with `-j 8`, memory usage stays around 8GB, allowing for standard parallel processing.

## How It Works and Output Results

When the tool is executed, it automatically searches for and validates `*.ann` and `*.fasta` file pairs in the specified directory. Once validation is complete, the following directory structure is generated in the output directory (or in the same directory as the target files if no output directory is specified).

* `reports/`: Stores text reports of the validation results.
    * `validation_report_summary.txt`: A summary of errors (ERROR/FATAL) and warnings (WARNING). You can check the number of occurrences per rule.
    * `validation_report_details.txt`: A full list of messages and line numbers where errors or warnings occurred.
    * `autofix_confirmation_summary.txt`: A list of proposed automatic fixes (Autofix).
* `fixed/`: Stores files reflecting the approved Autofixes (or those automatically applied via the `-f` option).
* `aa/`: Stores amino acid sequences (FASTA format) translated from CDS features.

## Acknowledgments

This project is built using the following open-source software. We deeply thank all developers and contributors to each of these projects.

* annotated-types
* anyio
* biopython
* certifi
* cffi
* charset-normalizer
* cryptography
* defusedxml
* distro
* geopandas
* google-auth
* google-genai
* h11
* httpcore
* httpx
* idna
* intervaltree
* numpy
* packaging
* pandas
* psycopg2-binary
* pyarrow
* pyasn1
* pyasn1_modules
* pycparser
* pydantic
* pydantic_core
* pyogrio
* pyproj
* python-dateutil
* python-dotenv
* requests
* shapely
* six
* sniffio
* sortedcontainers
* tenacity
* toml
* typing-inspection
* typing_extensions
* urllib3
* websockets