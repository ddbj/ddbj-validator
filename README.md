# BSI Validator

BSI Validator は、DDBJ (DNA Data Bank of Japan) に登録するアノテーションファイル（`.ann`）と塩基配列 FASTA ファイル（`.fasta`）の構文や整合性を検証・自動修正するためのコマンドラインツールです。  
本ツールはローカルでのフォーマットチェックに加え、NCBI Taxonomy API と連携し、登録前の詳細なバリデーション（Taxonomy に依存した整合性確認など）を行うことができます。  
DDBJ の既存チェックツールである [UME](https://www.ddbj.nig.ac.jp/ddbj/ume.html) の構文検証機能に加え、Taxonomy に依存した検証や [INSDC Minimal Specifications](https://www.insdc.org/insdc-minimal-specifications/) で定義されたチェック機能を提供しています。

## ルールリスト

現在適用されているバリデーションルールの詳細については、以下のスプレッドシートをご参照ください。
* [Validation Rules](https://docs.google.com/spreadsheets/xxx)

## インストール

### Docker のインストール

本ツールを実行するには、環境に Docker がインストールされている必要があります。

* Windows/macOS: [Docker Desktop](https://www.docker.com/products/docker-desktop/) をインストールしてください。
* Linux: (Docker Engine)[https://docs.docker.com/engine/install/] をインストールしてください。

### Docker イメージの取得

以下のコマンドで最新のイメージを取得します。
```bash
docker pull ghcr.io/ddbj/bsi-validator:0.1.0-beta
```

## 使い方

### ラッパースクリプトを使用する（推奨）

リポジトリに含まれるスクリプトを使用すると、複雑な Docker コマンドを入力せずに実行できます。

#### macOS/Linux (Unix 系)

`bsi-validator-ddbj.sh` があるディレクトリで実行します。

```bash
# 実行権限を付与（初回のみ）
chmod +x bsi-validator-ddbj.sh

# 実行（カレントディレクトリのファイルを検証）
./bsi-validator-ddbj.sh [オプション] [検証対象ディレクトリ]
```

#### Windows

コマンドプロンプトまたは PowerShell で `bsi-validator-ddbj.bat` を実行します。

```bash
bsi-validator-ddbj.bat [オプション] [検証対象ディレクトリ]
```

### Docker コマンドを直接実行する

スクリプトを使わず、直接 `docker run` で実行する場合の基本構造は以下の通りです。カレントディレクトリをコンテナ内の `/data` にマウントして実行します。

```bash
# macOS/Linux
docker run --rm -v $(pwd):/data ghcr.io/ddbj/bsi-validator:0.1.0-beta ddbj [オプション] /data

# Windows (PowerShell)
docker run --rm -v "${PWD}:/data" ghcr.io/ddbj/bsi-validator:0.1.0-beta ddbj [オプション] /data
```

### 主要なコマンドラインオプション

オプション説明
* -o, --out-dir レポート結果（Summary, Details）や自動修正済みファイルの出力先ディレクトリを指定します。
* -n, --ncbi-api(推奨) 公開の NCBI API を利用して Taxonomy の検証を行います。DDBJ のデータベースへの接続はスキップされます。
* -l, --local 完全にローカルな環境で動作します。DB および API へのアクセスをスキップし、ファイルのチェックのみを行います。
* -f, --force-fix フォーマットエラーや修正事項（Autofix）が見つかった際、対話プロンプトでの確認をスキップしてすべて自動適用します。
* --ncbi-api-key NCBI API へのリクエスト制限を緩和するための API キーを指定します。

#### 実行例（オプション指定）

NCBI API を利用し、結果を output フォルダに出力する場合（macOS/Linux の例）：
```bash
# macOS/Unix
./bsi-validator-ddbj.sh -n -o output_directory target_directory_contains_ann_fasta

# Windows
./bsi-validator-ddbj.bat -n -o output_directory target_directory_contains_ann_fasta
```

### 動作の仕組みと出力結果

ツールを実行すると、指定したディレクトリ内の *.ann と *.fasta のペアを自動的に検索し、検証を行います。
検証が完了すると、以下のファイルが出力ディレクトリ（指定がない場合は対象ファイルと同じディレクトリ）に生成されます。

* `validation_report_summary.txt`: エラーや警告のサマリー（ルールごとの発生件数）
* `validation_report_details.txt`: エラーが発生した行番号や具体的なメッセージ、修正指示などの詳細
* `fixed/` ディレクトリ: Autofix（自動修正）を承認、または --force-fix を指定した場合に出力される、修正済みのアノテーションおよび FASTA ファイル
* `aa/` ディレクトリ: CDS feature から翻訳されたアミノ酸配列（FASTA 形式）


