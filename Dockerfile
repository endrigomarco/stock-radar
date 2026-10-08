# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 AS uv

FROM python:3.13-slim-trixie@sha256:bf44cdfcb76cd3b41e879bc058fc37ec5872002ccfde7fcb765e218cde0cd79c AS tooling
COPY --from=uv /uv /uvx /usr/local/bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/tmp/uv-cache \
    TZ=UTC

WORKDIR /app
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home app \
    && mkdir -p /var/log/stock-radar \
    && chown app:app /app /var/log/stock-radar
USER app
CMD ["uv", "--version"]

FROM tooling AS runtime
COPY --chown=app:app pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-cache
COPY --chown=app:app src/ ./src/
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app migrations/ ./migrations/
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src"

# Infrastructure only. Replace with the application entrypoint when implemented.
CMD ["python", "--version"]

FROM runtime AS tests
RUN uv sync --locked --no-cache
