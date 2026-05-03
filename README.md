# BSI Validator

BSI Validator は、DDBJ (DNA Data Bank of Japan) に登録するアノテーションファイル（`.ann`）と塩基配列 FASTA ファイル（`.fasta`）の構文や整合性を検証・自動修正するためのコマンドラインツールです。  
本ツールはローカルでのフォーマットチェックに加え、NCBI Taxonomy API と連携し、登録前の詳細なバリデーション（Taxonomy に依存した整合性確認など）を行うことができます。  
DDBJ の既存チェックツールである [UME](https://www.ddbj.nig.ac.jp/ddbj/ume.html) の構文チェック機能に加え、Taxonomy に依存した確認や [INSDC Minimal Specifications](https://www.insdc.org/insdc-minimal-specifications/) で定められた要件を検証する機能を提供しています。

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
docker pull ghcr.io/ddbj/bsi-validator:0.1.0-beta
```

## 使い方

### A. ラッパースクリプトを使用する（推奨）

リポジトリに含まれるスクリプトを使用すると、複雑な Docker コマンドを入力せずに実行できます。

#### macOS/Linux (Unix 系)

`bsi-validator-ddbj.sh` があるディレクトリで実行します。

```bash
# 実行権限を付与（初回のみ）
chmod +x bsi-validator-ddbj.sh

# 実行（カレントディレクトリのファイルを検証）
./bsi-validator-ddbj.sh [オプション] [検証対象ディレクトリ]
```

対象ディレクトリを省略した場合、カレントディレクトリが対象となります。

#### Windows

コマンドプロンプトまたは PowerShell で `bsi-validator-ddbj.bat` を実行します。

```bash
bsi-validator-ddbj.bat [オプション] [検証対象ディレクトリ]
```

### B. Docker コマンドを直接実行する

直接 `docker run` で実行する場合の基本構造は以下の通りです。検証したいファイルが存在するディレクトリをコンテナ内の `/data` にマウントして実行します。

```bash
# macOS/Linux
docker run --rm -v $(pwd):/data ghcr.io/ddbj/bsi-validator:0.1.0-beta ddbj [オプション] /data

# Windows (PowerShell)
docker run --rm -v "${PWD}:/data" ghcr.io/ddbj/bsi-validator:0.1.0-beta ddbj [オプション] /data
```

### 主要なコマンドラインオプション

オプション説明
* `-o`, `--out-dir` レポート結果（Summary, Details）や自動修正済みファイルの出力先ディレクトリを指定します。
* `-n`, `--ncbi-api` (推奨) NCBI API を利用して Taxonomy の検証を行います。DDBJ のデータベースへの接続はスキップされます。
* `-l`, `--local` 完全にローカルな環境で動作します。DB および API へのアクセスをスキップし、ファイルのチェックのみを行います。
* `-f`, `--force-fix` フォーマットエラーや修正事項（Autofix）が見つかった際、対話プロンプトでの確認をスキップしてすべて自動適用します。
* `--ncbi-api-key` NCBI API へのリクエスト制限を緩和するための API キーを指定します。

#### 実行例（オプション指定）

NCBI API（`-n`）を利用し、結果を output（`-o`）フォルダに出力する場合：
```bash
# macOS/Unix
./bsi-validator-ddbj.sh -n -o output_directory target_directory_contains_ann_fasta

# Windows
./bsi-validator-ddbj.bat -n -o output_directory target_directory_contains_ann_fasta
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

| Package | Version | License |
| :--- | :--- | :--- |
| `annotated-types` | 0.7.0 | MIT |
| `anyio` | 4.12.1 | MIT |
| `biopython` | 1.86 | Biopython License |
| `certifi` | 2026.2.25 | MPL 2.0 |
| `cffi` | 2.0.0 | MIT |
| `charset-normalizer` | 3.4.6 | MIT |
| `cryptography` | 46.0.5 | Apache-2.0 / BSD |
| `defusedxml` | 0.7.1 | PSF License |
| `distro` | 1.9.0 | Apache-2.0 |
| `geopandas` | 1.1.3 | BSD |
| `google-auth` | 2.49.1 | Apache-2.0 |
| `google-genai` | 1.68.0 | Apache-2.0 |
| `h11` | 0.16.0 | MIT |
| `httpcore` | 1.0.9 | BSD |
| `httpx` | 0.28.1 | BSD |
| `idna` | 3.11 | BSD |
| `intervaltree` | 3.2.1 | Apache-2.0 |
| `numpy` | 2.4.2 | BSD / MIT / Zlib / CC0 |
| `packaging` | 26.2 | Apache-2.0 / BSD |
| `pandas` | 3.0.2 | BSD |
| `psycopg2-binary` | 2.9.11 | LGPL (with exception) |
| `pyarrow` | 24.0.0 | Apache-2.0 |
| `pyasn1` | 0.6.3 | BSD |
| `pyasn1_modules` | 0.4.2 | BSD |
| `pycparser` | 3.0 | BSD |
| `pydantic` | 2.12.5 | MIT |
| `pydantic_core` | 2.41.5 | MIT |
| `pyogrio` | 0.12.1 | MIT |
| `pyproj` | 3.7.2 | MIT |
| `python-dateutil` | 2.9.0.post0 | Apache-2.0 / BSD |
| `python-dotenv` | 1.2.2 | BSD |
| `requests` | 2.32.5 | Apache-2.0 |
| `shapely` | 2.1.2 | BSD |
| `six` | 1.17.0 | MIT |
| `sniffio` | 1.3.1 | Apache-2.0 / MIT |
| `sortedcontainers` | 2.4.0 | Apache-2.0 |
| `tenacity` | 9.1.4 | Apache-2.0 |
| `typing-inspection` | 0.4.2 | MIT |
| `typing_extensions` | 4.15.0 | PSF-2.0 |
| `urllib3` | 2.6.3 | MIT |
| `websockets` | 16.0 | BSD |




