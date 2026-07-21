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
- **Overview** — single-pane executive view: backend/DB up, request rate, 5xx rate, p95 latency, business actions, top features, most active orgs
- **Business Activity** — *what actions are performed & which features are most used*: actions over time by type, most-used features, top users, most active orgs, logins/exports/deletes, and support-access (superuser→customer) events. **Reads the `core_auditlog` table directly** via the Audit Postgres datasource.
- **Errors & Reliability** — *what breaks*: 5xx/4xx rates, responses by status, top failing endpoints, slowest endpoints (p95 by view), DB rollbacks/deadlocks, and the ERROR/CRITICAL log stream.
- **Django API** — request rate, latency (p50/p95/p99), error rate, top views
- **PostgreSQL** — connections, transactions, cache hit ratio, tuples, deadlocks, DB size
- **Uptime & Logs** — health-probe status/duration + live backend log stream

The **Overview**, **Business Activity**, and **Errors & Reliability** dashboards are scoped to **production** (Railway). See "Audit Postgres datasource" and "Monitoring production" below to wire up the connection.

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
cp .env.example .env          # fill AUDIT_DB_* (prod Railway DB) + Grafana password
docker compose up -d
```

Then open **http://localhost:3001** → the dashboards are already there.

> The **Business Activity / Overview** dashboards and the `postgres-exporter` read
> the DB configured by the `AUDIT_DB_*` vars in `.env` — point these at your
> **production Railway Postgres** (see "Audit Postgres datasource" below). If you
> leave them unset they fall back to a local `localhost:5432` DB.

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

## Audit Postgres datasource (Business Activity dashboards)

The **Business Activity** and **Overview** dashboards query the `core_auditlog`
table directly through a Grafana **PostgreSQL datasource** ("Audit Postgres", uid
`audit-postgres`). This is where every mutating action, login/logout, export, and
support-access event is recorded — the source for *"actions performed"* and
*"most-used features"*.

**1. Create a read-only DB role** (run once against the Railway DB; RLS matters —
see the warning below):

```sql
CREATE ROLE grafana_ro WITH LOGIN PASSWORD 'choose-a-strong-password';
GRANT CONNECT ON DATABASE railway TO grafana_ro;   -- Railway's DB is usually "railway"
GRANT USAGE ON SCHEMA public TO grafana_ro;
GRANT SELECT ON core_auditlog TO grafana_ro;
ALTER ROLE grafana_ro BYPASSRLS;                   -- see RLS warning below
```

> ⚠️ **Row-Level Security (RLS):** production Postgres enforces RLS keyed on the
> per-request `app.current_org_id` GUC. If the datasource role is *subject* to RLS,
> audit queries can silently return **0 rows** even though the data is there. Grant
> `BYPASSRLS` (needs a superuser to grant), **or** connect the datasource with the
> Railway DB owner/superuser role (which bypasses RLS). `core_auditlog` is not a
> tenant table, but this guarantees correctness regardless of any policy on it.

**2. Fill `AUDIT_DB_*` in `.env`** with the Railway **public TCP proxy** endpoint
(Railway → Postgres service → *Connect* → "Public Network" gives host/port/db):

```
AUDIT_DB_HOST=containers-us-west-xx.railway.app
AUDIT_DB_PORT=6543
AUDIT_DB_NAME=railway
AUDIT_DB_USER=grafana_ro
AUDIT_DB_PASSWORD=...
AUDIT_DB_SSLMODE=require
```

These same vars point the **postgres-exporter** at prod too, so the PostgreSQL
dashboard and the "Database down" alert reflect production.

**3. Verify:** Grafana → *Connections → Data sources → Audit Postgres → Test*.
A green result means creds + SSL + RLS-bypass all work and the dashboards will populate.

## Alerting

Five alert rules are pre-provisioned (Grafana → *Alerting → Alert rules*, folder
**Audity Alerts**):

| Rule | Fires when |
|---|---|
| High 5xx error rate | 5xx ratio > 5% for 5m |
| Backend down | health probe failing for 2m |
| Database down | `pg_up = 0` for 2m |
| High p95 latency | p95 > 2s for 10m |
| No production traffic | request rate ~0 for 10m |

All route to the **audity-default** contact point. To actually receive
notifications, enable email delivery by setting these in `.env` (then
`docker compose up -d` to apply):

```
GF_SMTP_ENABLED=true
GF_SMTP_HOST=smtp.yourprovider.com:587
GF_SMTP_USER=...
GF_SMTP_PASSWORD=...
GF_SMTP_FROM_ADDRESS=alerts@audity.app
ALERT_EMAIL_TO=you@audity.app
```

Prefer Slack? Uncomment the `slack` receiver in
[`grafana/provisioning/alerting/contactpoints.yml`](grafana/provisioning/alerting/contactpoints.yml)
and paste your webhook URL.

## Monitoring production (Railway)

Metrics and uptime for prod are **already wired** — `prometheus/prometheus.yml`
has `django-production` (`/metrics` over https) and `blackbox-production` (health
probe) scrape jobs. The DB + audit data is covered by the `AUDIT_DB_*` config
above. The only gap:

- **Logs** — Promtail tailing local files won't see Railway logs; the ERROR log
  panels reflect a locally-run backend. For prod exception detail, set `SENTRY_DSN`
  on the backend and use Sentry, or ship Railway logs to Loki via a log drain.

For always-on prod monitoring, host this stack on a small VM or use **Grafana
Cloud** rather than your laptop. Lock `/metrics` down first (see Security notes).

## Optional: richer database query metrics

`django-prometheus` can also instrument the ORM (per-query counts/latency) by
switching the DB engine to `django_prometheus.db.backends.postgresql`. It's left
off here to avoid touching the DB layer; `postgres_exporter` already covers
server-side DB health. Enable it only if you want app-side query metrics too.
