# DDBJ Validator

DDBJ Validator は、DDBJ (DNA Data Bank of Japan) に登録するアノテーションファイル（`.ann`）と塩基配列 FASTA ファイル（`.fasta`）の構文や整合性を検証・自動修正するためのコマンドラインツールです。  
本ツールはローカルでのフォーマットチェックに加え、NCBI Taxonomy API と連携し、登録前の詳細なバリデーション（Taxonomy に依存した整合性確認など）を行うことができます。  
DDBJ の既存チェックツールである [jParser](https://www.ddbj.nig.ac.jp/ddbj/parser.html) による構文チェック、[transChecker](https://www.ddbj.nig.ac.jp/ddbj/transchecker.html) による CDS アミノ酸翻訳機能に加え、Taxonomy に依存した確認や [INSDC Minimal Specifications](https://www.insdc.org/insdc-minimal-specifications/) で定められた要件を検証する機能を提供しています。

## ルールリスト

現在適用されているバリデーションルールの詳細については、スプレッドシート [Validation rules](https://docs.google.com/spreadsheets/xxx)をご参照ください。

## インストール

### Docker のインストール

本ツールを実行するには、Docker がインストールされている必要があります。

* Windows/macOS: [Docker Desktop](https://www.docker.com/products/docker-desktop/) をインストールしてください。
* Linux: [Docker Engine](https://docs.docker.com/engine/install/) をインストールしてください。

### Docker イメージの取得

以下のコマンドで最新のイメージを取得します。
```bash
docker pull ghcr.io/ddbj/ddbj-validator:0.1.0-beta
```

## 使い方

### A. ラッパースクリプトを使用する（推奨）

リポジトリに含まれるスクリプトを使用すると、複雑な Docker コマンドを入力せずに実行できます。

#### macOS/Linux (Unix 系)

`ddbj-validator-seq.sh` があるディレクトリで実行します。

```bash
# 実行権限を付与（初回のみ）
chmod +x ddbj-validator-seq.sh

# 実行（カレントディレクトリのファイルを検証）
./ddbj-validator-seq.sh [オプション] [検証対象ディレクトリ]
```

対象ディレクトリを省略した場合、カレントディレクトリが対象となります。

#### Windows

コマンドプロンプトまたは PowerShell で `ddbj-validator-seq.bat` を実行します。

```bash
ddbj-validator-seq.bat [オプション] [検証対象ディレクトリ]
```

### B. Docker コマンドを直接実行する

直接 `docker run` で実行する場合の基本構造は以下の通りです。検証したいファイルが存在するディレクトリをコンテナ内の `/data` にマウントして実行します。

```bash
# macOS/Linux
docker run --rm -v $(pwd):/data ghcr.io/ddbj/ddbj-validator:0.1.0-beta ddbj [オプション] /data

# Windows (PowerShell)
docker run --rm -v "${PWD}:/data" ghcr.io/ddbj/ddbj-validator:0.1.0-beta ddbj [オプション] /data
```

### 主要なコマンドラインオプション

オプション説明
* `-o`, `--out-dir` レポート結果（Summary, Details）や自動修正済みファイルの出力先ディレクトリを指定します。
* `-n`, `--ncbi-api` (推奨) NCBI API を利用して Taxonomy の検証を行います。DDBJ のデータベースへの接続はスキップされます。
* `-l`, `--local` 完全にローカルな環境で動作します。DB および API へのアクセスをスキップし、ファイルのチェックのみを行います。
* `-f`, `--force-fix` フォーマットエラーや修正事項（Autofix）が見つかった際、対話プロンプトでの確認をスキップしてすべて自動適用します。
* `-j`, `--jobs` 並列処理するプロセス数を指定します。指定しない場合は環境に合わせて自動設定されます（最大8）。`0` を指定すると、利用可能なすべての CPU コアを使用します。
* `--ncbi-api-key` NCBI API へのリクエスト制限を緩和するための API キーを指定します。

### メモリ使用量

本ツールは並列数に比例してメモリを消費します。1プロセスあたりのメモリ使用量は、対象となる個別の FASTA ファイルサイズに大きく依存します。メモリ不足（OOM）による強制終了を防ぐため、以下の目安を参考に `-j` の数値を調整してください。

【メモリ消費の目安（実測値）】
* 巨大な配列データ（FASTA が数GBクラス/ヒトゲノム等）
  * 1ファイル（約3GB）の処理につき、約15GB〜18GB のメモリを消費します。
  * `-j 4` では約55GB、`-j 8` では約100GBのRAMが必要になります。
* 小さな配列データ群（FASTA が数十〜数百MBクラス/TSA や短いアセンブリ等）
  * 1ファイル（約100MB）の処理につき、約1.5GB〜2GB のメモリを消費します。
  * `-j 8` でも約8GB程度に収まるため、標準的な並列処理が可能です。
  
#### 実行例（オプション指定）

NCBI API（`-n`）を利用し、結果を output（`-o`）フォルダに出力する場合：
```bash
# macOS/Unix
./ddbj-validator-seq.sh -n -o output_directory target_directory_contains_ann_fasta

# Windows
./ddbj-validator-seq.bat -n -o output_directory target_directory_contains_ann_fasta
```

### 動作の仕組みと出力結果

ツールを実行すると、指定したディレクトリ内の *.ann と *.fasta のペアを自動的に検索し、検証を行います。
検証が完了すると、出力ディレクトリ（指定がない場合は対象ファイルと同じディレクトリ）に以下のフォルダ群が生成されます。

生成ディレクトリとファイル
* `reports/` 検証結果の各種レポートテキストが格納されます。
    * `validation_report_summary.txt`: エラー（ERROR/FATAL）や警告（WARNING）のサマリー です。ルールごとの発生件数を確認できます。
    * `validation_report_details.txt`: エラーや警告が発生した行番号やメッセージの全リストです。
    * `autofix_confirmation_summary.txt`: Autofix（自動修正）の提案一覧です。
* `fixed/` 承認された Autofix（または、`-f` オプションで自動適用された修正）が反映されたファイルが格納されます。
* `aa/` CDS feature から翻訳されたアミノ酸配列（FASTA 形式）が格納されます。

# DDBJ Validator

The DDBJ Validator is a command-line tool to validate and automatically fix the syntax and consistency of annotation files (`.ann`) and nucleotide sequence FASTA files (`.fasta`) for submission to the DDBJ (DNA Data Bank of Japan).  
In addition to format validation, this tool uses the NCBI Taxonomy API to perform detailed validation such as taxonomy-dependent checks before submission.  
Alongside the syntax validation by DDBJ's existing tool [jParser](https://www.ddbj.nig.ac.jp/ddbj/parser-e.html) and the CDS amino acid translation features of [transChecker](https://www.ddbj.nig.ac.jp/ddbj/transchecker-e.html), this tool provides taxonomy-dependent validations and checks required by the [INSDC Minimal Specifications](https://www.insdc.org/insdc-minimal-specifications/).

## Rule List

For details on the validation rules, please refer to the spreadsheet [Validation rules](https://www.google.com/search?q=https://docs.google.com/spreadsheets/xxx).

## Installation

### Installing Docker

Docker must be installed to run this tool.

* Windows/macOS: Please install [Docker Desktop](https://www.docker.com/products/docker-desktop/).
* Linux: Please install [Docker Engine](https://docs.docker.com/engine/install/).

### Downloading the Docker Image

Download the latest image using the following command:

```bash
docker pull ghcr.io/ddbj/ddbj-validator:0.1.0-beta
```

## Usage

### A. Using the Wrapper Script (Recommended)

You can execute the tool without entering complex Docker commands by using the scripts included in the repository.

#### macOS/Linux (Unix-like)

Execute the script in the directory where `ddbj-validator-seq.sh` is located.

```bash
# Grant execution permission (first time only)
chmod +x ddbj-validator-seq.sh

# Execute (validates files in the current directory)
./ddbj-validator-seq.sh [Options] [Target Directory]
```

If the target directory is omitted, the current directory will be validated.

#### Windows

Execute `ddbj-validator-seq.bat` in the Command Prompt or PowerShell.

```bash
ddbj-validator-seq.bat [Options] [Target Directory]
```

### B. Running Docker Commands Directly

The basic structure for executing the tool directly via `docker run` is as follows. Mount the directory containing the files you want to validate to `/data` inside the container.

```bash
# macOS/Linux
docker run --rm -v $(pwd):/data ghcr.io/ddbj/ddbj-validator:0.1.0-beta ddbj [Options] /data

# Windows (PowerShell)
docker run --rm -v "${PWD}:/data" ghcr.io/ddbj/ddbj-validator:0.1.0-beta ddbj [Options] /data
```

### Main Command-Line Options

Options

* `-o`, `--out-dir`: Specifies the output directory for the report files (summary, details) and auto-fixed files.
* `-n`, `--ncbi-api`: (Recommended) Uses the NCBI API for Taxonomy validation. Skips access to the DDBJ databases.
* `-l`, `--local`: Runs in a completely local environment. Skips access to databases and APIs, performing only file checks.
* `-f`, `--force-fix`: Automatically applies all fixes (Autofix) found, skipping the interactive confirmation prompt.
* `-j`, `--jobs`: Specifies the number of parallel processes. If not specified, it is automatically set according to the environment (maximum of 8). If `0` is specified, all available CPU cores will be used.
* `--ncbi-api-key`: Specifies an API key to ease request limits to the NCBI API.

### Memory Usage

This tool consumes memory proportional to the number of parallel processes. The memory usage per process is highly dependent on the size of the individual FASTA file being processed. To prevent forced termination due to Out of Memory (OOM) errors, please adjust the `-j` value using the following guidelines.

[Memory Consumption Guidelines (Measured Values)]

* Large sequence data (FASTA files in the gigabyte range/Human genome, etc.)
    * Processing 1 file (approx. 3GB) consumes about 15GB to 18GB of memory.
    * `-j 4` requires about 55GB, and `-j 8` requires about 100GB of RAM.
* Small sequence data sets (FASTA files in the tens to hundreds of megabytes range/TSA, short assemblies, etc.)
    * Processing 1 file (approx. 100MB) consumes about 1.5GB to 2GB of memory.
    * Even with `-j 8`, memory usage stays around 8GB, allowing for standard parallel processing.

#### Execution Example (with options)

When using the NCBI API (`-n`) and outputting results to an `output_directory` (`-o`):

```bash
# macOS/Unix
./ddbj-validator-seq.sh -n -o output_directory target_directory_contains_ann_fasta

# Windows
./ddbj-validator-seq.bat -n -o output_directory target_directory_contains_ann_fasta
```

### How It Works and Output Results

When the tool is executed, it automatically searches for and validates `*.ann` and `*.fasta` file pairs in the specified directory. Once validation is complete, the following directory structure is generated in the output directory (or in the same directory as the target files if no output directory is specified).

Generated directories and files

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
* typing-inspection
* typing_extensions
* urllib3
* websockets