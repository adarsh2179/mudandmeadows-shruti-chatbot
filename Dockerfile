# ==============================================================================
# Mud & Meadows Autonomous AI Concierge Dockerfile
# Production-ready, secure, lightweight multi-stage container build
# ==============================================================================

FROM python:3.11-slim AS builder

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install build dependencies for C extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies to wheels directory
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


# ==============================================================================
# Final Runtime Stage
# ==============================================================================
FROM python:3.11-slim AS runner

WORKDIR /app

# Create non-privileged system user and writable SQLite data directory
RUN groupadd -r appuser && useradd -r -g appuser appuser \
    && mkdir -p /app/data && chown -R appuser:appuser /app

# Copy installed python packages from builder
COPY --from=builder /root/.local /home/appuser/.local

# Ensure python binary path includes user site-packages
ENV PATH=/home/appuser/.local/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    SESSION_DB_PATH=/app/data/concierge_state.db

# Copy application source code and assets
COPY --chown=appuser:appuser config.py .
COPY --chown=appuser:appuser session_store.py .
COPY --chown=appuser:appuser resort_client.py .
COPY --chown=appuser:appuser pricing_engine.py .
COPY --chown=appuser:appuser voice_service.py .
COPY --chown=appuser:appuser notification_service.py .
COPY --chown=appuser:appuser agent.py .
COPY --chown=appuser:appuser main.py .
COPY --chown=appuser:appuser static/ ./static/

# Switch to unprivileged runtime user
USER appuser

# Expose HTTP port
EXPOSE 8000

# Container healthcheck against /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Start Uvicorn ASGI production server honoring platform-injected $PORT
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
