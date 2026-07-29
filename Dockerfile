FROM python:3.14-alpine AS builder

WORKDIR /app

RUN apk add --no-cache build-base libffi-dev
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /bin/uv

ENV UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    UV_PYTHON_DOWNLOADS=0

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

FROM python:3.14-alpine

WORKDIR /app

RUN apk add --no-cache libffi \
    && adduser -D appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app

COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --chown=appuser:appuser bot ./bot
COPY --chown=appuser:appuser store_data_extractor ./store_data_extractor
COPY --chown=appuser:appuser utils ./utils
COPY --chown=appuser:appuser __init__.py main_file.py run.py ./

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER appuser

CMD ["python", "run.py"]
