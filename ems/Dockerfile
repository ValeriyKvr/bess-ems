FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install uv and system dependencies
COPY --from=ghcr.io/astral-sh/uv:0.4.10 /uv /bin/uv

# Copy project definition
COPY pyproject.toml README.md alembic.ini ./

# Install dependencies into system Python
RUN uv pip install --system --no-cache -r pyproject.toml

# Install runtime libraries (libgomp1 required for LightGBM OpenMP)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy source code
COPY ems/ ems/

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=5s --timeout=5s --start-period=10s --retries=10 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

CMD ["python", "-m", "uvicorn", "ems.main:app", "--host", "0.0.0.0", "--port", "8000"]
