# ============================================================
# Finventory - Production Dockerfile
# Multi-stage build: keeps final image lean (~300MB vs ~1GB)
# ============================================================

# ── Stage 1: Builder ─────────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies into a prefix dir for clean copying
COPY backend/requirements/production.txt ./requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: Runtime ──────────────────────────────────────────
FROM python:3.13-slim AS runtime

# Security: Run as non-root user
RUN groupadd -r finventory && useradd -r -g finventory finventory

WORKDIR /app

# Runtime system deps only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY backend/ ./backend/
COPY .env.example .env.example

# Create required directories
RUN mkdir -p backend/logs backend/media backend/staticfiles \
    && chown -R finventory:finventory /app

USER finventory

WORKDIR /app/backend

# Collect static files
RUN python manage.py collectstatic --noinput --settings=config.settings.production 2>/dev/null || true

EXPOSE 8000

# Gunicorn with 4 workers per CPU core (adjust for your instance)
CMD ["gunicorn", \
    "--bind", "0.0.0.0:8000", \
    "--workers", "4", \
    "--worker-class", "sync", \
    "--worker-tmp-dir", "/dev/shm", \
    "--access-logfile", "-", \
    "--error-logfile", "-", \
    "--log-level", "info", \
    "--timeout", "30", \
    "config.wsgi:application"]
