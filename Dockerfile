FROM python:3.11-slim

LABEL maintainer="BioData Science Initiative (BSI)"
LABEL description="BSI Validation Tools"

# Pythonの動作設定（標準出力をバッファリングしない、pycを作らない）
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 必要なシステムパッケージのインストール（psycopg2等のビルドに必要な場合）
# 不要なキャッシュを削除してイメージサイズを抑える
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 作業ディレクトリの設定
WORKDIR /app

# 依存関係ファイルのコピーとインストール
# キャッシュを有効活用するため、ソースコードより先にコピー
COPY pyproject.toml requirements.txt* ./
RUN if [ -f "requirements.txt" ]; then \
        pip install --no-cache-dir -r requirements.txt; \
    else \
        pip install --no-cache-dir . ; \
    fi

# プロジェクトのソースコードをすべてコピー
COPY . .

# 一般ユーザーがマウントしたディレクトリにアクセスできるよう、
# 実行時のカレントディレクトリ（/work）を作成しておく
WORKDIR /work

# コンテナ起動時のデフォルトコマンドを設定
# これにより、`docker run <image> ddbj <target>` のようにコマンドラインツールとして振る舞う
ENTRYPOINT ["python", "/app/main.py"]