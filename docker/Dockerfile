FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock* README.md ./
COPY src ./src
COPY configs ./configs
COPY docker/entrypoint.sh /entrypoint.sh

RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && /root/.local/bin/uv sync --no-dev

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uv", "run", "adda", "retrieve", "glioblastoma", "--max-results", "20"]

