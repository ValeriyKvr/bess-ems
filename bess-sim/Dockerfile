FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.4.10 /uv /bin/uv

# Copy project definition
COPY pyproject.toml README.md ./

# Install dependencies into system environment
RUN uv pip install --system --no-cache -r pyproject.toml

# Copy source code
COPY bess_sim/ bess_sim/

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app /tmp
USER appuser

HEALTHCHECK --interval=5s --timeout=5s --start-period=5s --retries=10 \
    CMD python -c "import os; exit(0 if os.path.exists('/tmp/healthy') else 1)"

CMD ["python", "-m", "bess_sim.main"]
