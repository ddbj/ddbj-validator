# BSI Validator

BSI Validator は、DDBJ (DNA Data Bank of Japan) に登録するアノテーションファイル（`.ann`）と塩基配列 FASTA ファイル（`.fasta`）の構文や整合性を検証・自動修正するためのコマンドラインツールです。  
本ツールはローカルでのフォーマットチェックに加え、NCBI Taxonomy API と連携し、登録前の詳細なバリデーション（Taxonomy に依存した整合性確認など）を行うことができます。

## ルールリスト

現在適用されているバリデーションルールの詳細については、以下のスプレッドシートをご参照ください。
* [Validation Rules](https://docs.google.com/spreadsheets/xxx)

## 使い方 (Docker を利用した実行方法)

環境構築の手間を省くため、Docker イメージの利用を推奨しています。以下のコマンドでイメージをダウンロードできます。

```bash
docker pull ghcr.io/ddbj/bsi-validator:0.1.0-beta
```

### 基本的なコマンド構造

カレントディレクトリ（検証したい .ann と .fasta があるディレクトリ）を Docker コンテナ内の /data にマウントして実行します。  

```bash
docker run --rm -v <マウントするディレクトリ>:/data ghcr.io/ddbj/bsi-validator:0.1.0-beta ddbj [オプション] /data
```

#### macOS/Linux (Unix 系)

```bash
# 対象ディレクトリへ移動
cd /path/to/your/data

# バリデーションの実行
docker run --rm -v $(pwd):/data ghcr.io/ddbj/bsi-validator:0.1.0-beta ddbj /data
```

#### Windows (PowerShell)

```bash
cd C:\path\to\your\data
docker run --rm -v "${PWD}:/data" ghcr.io/ddbj/bsi-validator:0.1.0-beta ddbj /data
```

### 主要なコマンドラインオプション

オプション説明
-o, --out-dir レポート結果（Summary, Details）や自動修正済みファイルの出力先ディレクトリを指定します。
-n, --ncbi-api(推奨) 公開の NCBI API を利用して Taxonomy の検証を行います。DDBJ のデータベースへの接続はスキップされます。
-l, --local 完全にローカルな環境で動作します。DB および API へのアクセスをスキップし、ファイルのチェックのみを行います。
-f, --force-fix フォーマットエラーや修正事項（Autofix）が見つかった際、対話プロンプトでの確認をスキップしてすべて自動適用します。
--ncbi-api-key NCBI API へのリクエスト制限を緩和するための API キーを指定します。

#### 実行例（オプション指定）

NCBI API を利用し、確認プロンプトなしで自動修正を適用、結果を output フォルダに出力する場合（macOS/Linux の例）：
```bash
docker run --rm -v $(pwd):/data ghcr.io/ddbj/bsi-validator:0.1.0-beta ddbj -n -f -o /data/output /data
```

### 動作の仕組みと出力結果

ツールを実行すると、指定したディレクトリ内の *.ann と *.fasta のファイルペアを自動的に検索し、検証を行います。
検証が完了すると、以下のファイルが出力ディレクトリ（指定がない場合は対象ファイルと同じディレクトリ）に生成されます。

validation_report_summary.txt: エラーや警告のサマリー（ルールごとの発生件数）
validation_report_details.txt: エラーが発生した行番号や具体的なメッセージ、修正指示などの詳細
fixed/ ディレクトリ: Autofix（自動修正）を承認、または --force-fix を指定した場合に出力される、修正済みのアノテーションおよび FASTA ファイル
aa/ ディレクトリ: CDS feature から翻訳されたアミノ酸配列（FASTA 形式）


