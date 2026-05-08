FROM python:3.12-slim

LABEL maintainer="DNA Data Bank of Japan (DDBJ)"
LABEL description="DDBJ Validation Tools"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml requirements.txt* ./

RUN if [ -f "requirements.txt" ]; then \
        pip install --no-cache-dir -r requirements.txt; \
    fi

COPY . .

RUN pip install --no-cache-dir .

RUN chmod +x /app/ddbj-validator-seq.sh

WORKDIR /work

ENTRYPOINT ["ddbj-validator"]