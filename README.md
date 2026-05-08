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
検証が完了すると、以下のファイルが出力ディレクトリ（指定がない場合は対象ファイルと同じディレクトリ）に生成されます。

生成ファイル
* `validation_report_summary.txt`: エラー（ERROR/FATAL）や警告（WARNING）のサマリー です。ルールごとの発生件数を確認できます。
* `validation_report_details.txt`: エラーや警告が発生した行番号やメッセージの全リストです。

生成ディレクトリ
* `fixed/` 承認された Autofix（または、`-f` オプションで自動適用された修正）が反映されたファイルが格納されます。
* `aa/` CDS feature から翻訳されたアミノ酸配列（FASTA 形式）が格納されます。

## 謝辞

本プロジェクトは、以下のオープンソースソフトウェアを利用して構築されています。各ソフトウェアの開発者および貢献者の皆様に深く感謝いたします。

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
