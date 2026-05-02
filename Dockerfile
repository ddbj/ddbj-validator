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

COPY pyproject.toml requirements.txt* ./

RUN if [ -f "requirements.txt" ]; then \
        pip install --no-cache-dir -r requirements.txt; \
    fi

COPY . .

RUN pip install --no-cache-dir .

RUN chmod +x /app/bsi-validator-ddbj.sh

WORKDIR /work

ENTRYPOINT ["bsi-validator"]