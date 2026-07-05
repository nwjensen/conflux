# Conflux — Phase 1 container image
FROM python:3.13-slim

# Calm, predictable runtime.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
COPY conflux/ ./conflux/

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 conflux \
    && mkdir -p /data && chown -R conflux:conflux /app /data
USER conflux

# Default to a writable on-disk SQLite DB inside the container's /data volume.
# In Compose this is overridden to point at PostgreSQL.
ENV CONFLUX_DATABASE_URL=sqlite:////data/conflux.db

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:8080/healthz').status==200 else sys.exit(1)"

CMD ["python", "-m", "uvicorn", "conflux.main:app", "--host", "0.0.0.0", "--port", "8080"]
