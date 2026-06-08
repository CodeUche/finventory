# Audity Observability Stack (Grafana)

Self-contained monitoring for the Audity backend: **metrics, logs, database, and uptime**, visualized in Grafana — all pre-provisioned, no manual clicking.

## What's included

| Service | Port | Purpose |
|---|---|---|
| **Grafana** | http://localhost:3001 | Dashboards (login: `admin` / `admin`) |
| **Prometheus** | http://localhost:9090 | Metrics collection |
| **Loki** | 3100 | Log aggregation |
| **Promtail** | — | Ships `backend/logs/*.log` into Loki |
| **postgres_exporter** | 9187 | PostgreSQL metrics |
| **blackbox_exporter** | 9115 | Uptime / health probing |

Pre-built dashboards (Grafana → Dashboards → **Audity** folder):
- **Django API** — request rate, latency (p50/p95/p99), error rate, top views
- **PostgreSQL** — connections, transactions, cache hit ratio, tuples, deadlocks, DB size
- **Uptime & Logs** — health-probe status/duration + live backend log stream

## Prerequisites

1. **Docker Desktop running.**
2. The backend exposes metrics at `/metrics` (already wired via `django-prometheus`).
   Install the new dependency once: `pip install -r backend/requirements/base.txt`
   (or `pip install django-prometheus`), then restart the backend.
3. Your Postgres is reachable on the host at `localhost:5432` (the main
   `docker-compose.yml` `db` service exposes it).

## Run it

```bash
cd finventory/observability
cp .env.example .env          # edit DB creds + Grafana password if needed
docker compose up -d
```

Then open **http://localhost:3001** → the dashboards are already there.

> The stack scrapes the **host** via `host.docker.internal`, so it works whether
> you run Django through the venv (`manage.py runserver`) or in Docker, and
> Postgres through the main compose. No shared Docker network needed.

To stop: `docker compose down` (add `-v` to also wipe stored metrics/logs).

## Verify it's working

- Prometheus targets all **UP**: http://localhost:9090/targets
- Raw metrics from Django: http://localhost:8000/metrics
- Grafana dashboards show data within ~30s of traffic hitting the API.

## Security notes

- `/metrics` is **unauthenticated by design** (Prometheus needs raw access).
  Locally that's fine. **Do not expose `/metrics` publicly in production** —
  restrict it at the network/proxy layer to the Prometheus host only.
- Change the Grafana admin password (`GF_ADMIN_PASSWORD` in `.env`) before
  running this anywhere other than your own machine.
- `.env` (real DB password) is gitignored — only `.env.example` is committed.

## Monitoring production (Railway) instead of local

This stack defaults to monitoring your **local** backend. To point it at prod:

1. **Metrics** — edit [`prometheus/prometheus.yml`](prometheus/prometheus.yml):
   change the `django` job target to your Railway host and set
   `scheme: https`. Lock `/metrics` down first (see Security notes).
2. **Database** — set `DATA_SOURCE_NAME` for `postgres-exporter` (in
   `docker-compose.yml`) to your Railway Postgres connection string.
3. **Uptime** — change the `blackbox-http` target in `prometheus.yml` to your
   public API URL (e.g. `https://audity-backend-production-30f9.up.railway.app/api/v1/health/`).
4. **Logs** — Promtail tailing local files won't see Railway logs; use Railway's
   log drains → Loki, or Grafana Cloud, instead.

For always-on prod monitoring you'd typically host this stack on a small VM or
use **Grafana Cloud** rather than your laptop.

## Optional: richer database query metrics

`django-prometheus` can also instrument the ORM (per-query counts/latency) by
switching the DB engine to `django_prometheus.db.backends.postgresql`. It's left
off here to avoid touching the DB layer; `postgres_exporter` already covers
server-side DB health. Enable it only if you want app-side query metrics too.
