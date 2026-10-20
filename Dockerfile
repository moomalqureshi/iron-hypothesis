FROM python:3.12-slim
ENV IRONMAN_MIGRATIONS_DIR=/app/migrations PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml README.md* ./
COPY src ./src
COPY migrations ./migrations
RUN uv pip install --system --no-cache ".[ml]" && useradd -r -u 10001 app
USER app
CMD ["uvicorn", "ironman.api:app", "--host", "0.0.0.0", "--port", "8000"]
