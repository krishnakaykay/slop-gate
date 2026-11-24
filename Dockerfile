FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/backend \
    DATA_DIR=/tmp/slop-gate-data \
    SESSION_TTL_HOURS=2 \
    SLOP_JSON_LOGS=true \
    PORT=8080

WORKDIR /app

# Install Python dependencies first for layer caching
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy application code, static frontend, and calibration sample PDFs
COPY backend /app/backend
COPY frontend /app/frontend
COPY examples /app/examples

# Run as non-root user with writable /tmp data directory
RUN useradd -m -u 10001 appuser && mkdir -p /tmp/slop-gate-data && chown -R appuser:appuser /app /tmp/slop-gate-data
USER appuser

EXPOSE 8080

# Single worker (--workers 1) keeps SQLite WAL and in-memory SSE streams consistent
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
