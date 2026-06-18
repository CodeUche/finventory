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
# Copy the whole requirements/ folder so -r base.txt resolves correctly
COPY backend/requirements/ ./requirements/
RUN pip install --no-cache-dir --prefix=/install -r requirements/production.txt

# ── Stage 2: Runtime ──────────────────────────────────────────
FROM python:3.13-slim AS runtime

# Security: Run as non-root user
RUN groupadd -r finventory && useradd -r -g finventory finventory

WORKDIR /app

# Runtime system deps: libpq5 for psycopg2, plus postgresql-client-18 (matching
# the Railway Postgres server's major version) so the db-backup-cron service's
# `pg_dump` command exists in PATH — pg_dump must match the server's major
# version or dumps can fail/be incomplete.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl ca-certificates gnupg lsb-release \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc --fail https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-18 \
    && apt-get purge -y --auto-remove curl gnupg lsb-release \
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

# Default CMD is the web server. worker and beat override this via
# Railway's "Start Command" setting — no `cd` needed since WORKDIR
# is already /app/backend.
# Use shell form (string) so Railway can also override with env vars.
CMD python manage.py migrate --no-input && \
    python manage.py collectstatic --no-input --clear 2>/dev/null; \
    if [ -n "$DJANGO_SUPERUSER_EMAIL" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then \
      python manage.py createsuperuser --no-input \
        --email "$DJANGO_SUPERUSER_EMAIL" 2>/dev/null || true; \
    fi; \
    gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-8000}" \
    --workers 2 --worker-class sync \
    --worker-tmp-dir /dev/shm \
    --access-logfile - --error-logfile - \
    --log-level info --timeout 120
