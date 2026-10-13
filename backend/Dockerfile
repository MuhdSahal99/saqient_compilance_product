# syntax=docker/dockerfile:1
FROM python:3.13-slim AS build
RUN pip install --no-cache-dir uv==0.11.32
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Optional extras, space separated (e.g. "vertex gcs"). None by default.
ARG EXTRAS=""
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project $(for e in $EXTRAS; do printf -- "--extra %s " "$e"; done)
COPY . .
RUN uv sync --frozen --no-dev $(for e in $EXTRAS; do printf -- "--extra %s " "$e"; done)

FROM python:3.13-slim
RUN groupadd --system app && useradd --system --gid app --home /app app \
    && mkdir -p /data/storage && chown app:app /data/storage
WORKDIR /app
COPY --from=build --chown=app:app /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 STORAGE_LOCAL_PATH=/data/storage
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
