# uv-managed image for the existing demo entrypoints.
FROM ghcr.io/astral-sh/uv:0.9.4 AS uv
FROM python:3.11-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /bin/
COPY . .
RUN uv sync --project backend --locked --no-dev

ENV PATH="/app/backend/.venv/bin:$PATH"

EXPOSE 8080 8501

CMD ["python", "app.py"]
