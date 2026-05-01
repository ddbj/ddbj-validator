FROM python:3.12-slim

LABEL maintainer="BioData Science Initiative (BSI)"
LABEL description="BSI Validation Tools"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依存関係ファイルを先にコピーしてキャッシュを効かせる
COPY pyproject.toml requirements.txt* ./

# まず requirements.txt で依存パッケージのみをインストール（レイヤーキャッシュ用）
RUN if [ -f "requirements.txt" ]; then \
        pip install --no-cache-dir -r requirements.txt; \
    fi

# プロジェクトのソースコード全体をコピー
COPY . .

# 2. bsi-validator 自身をパッケージとしてインストール！
# （これで pyproject.toml の [project.scripts] がシステムに登録される）
RUN pip install --no-cache-dir .

WORKDIR /work

# 3. pyproject.toml で作成したコマンド名をそのまま指定
ENTRYPOINT ["bsi-validator"]