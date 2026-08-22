# 依赖构建阶段：最终镜像只携带安装后的运行时文件。
FROM ghcr.io/astral-sh/uv:0.9.4 AS builder

FROM python:3.11-slim AS build

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY --from=builder /uv /uvx /bin/
COPY backend/pyproject.toml backend/uv.lock /app/backend/

RUN uv sync --project backend --locked --no-install-project --no-editable --no-dev

COPY backend/src /app/backend/src
COPY backend/alembic /app/backend/alembic
COPY backend/alembic.ini /app/backend/alembic.ini
COPY backend/config /app/backend/config

RUN uv sync --project backend --locked --no-editable --no-dev

FROM python:3.11-slim AS runtime

ARG APP_VERSION=dev

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH" \
    APP_VERSION=$APP_VERSION \
    PYTHONUNBUFFERED=1

COPY --from=build /app/backend/.venv /app/.venv
COPY --from=build /app/backend/alembic /app/alembic
COPY --from=build /app/backend/alembic.ini /app/alembic.ini
COPY --from=build /app/backend/config /app/config

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "chat_agents.main:app", "--host", "0.0.0.0", "--port", "8080"]
