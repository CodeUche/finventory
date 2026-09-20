"""
Gunicorn production configuration.

Auto-sizes workers to the available CPU count so the server scales
horizontally without manual tuning on different instance sizes.

Railway / Render: set $PORT via their dashboard (done automatically).
"""
import multiprocessing
import os

# ── Workers ────────────────────────────────────────────────────────────────────
# The classic formula: 2 × CPUs + 1  (I/O-bound Django workload)
workers = multiprocessing.cpu_count() * 2 + 1

# Threads per worker — allows each worker to serve multiple requests when one is
# waiting on DB/network I/O without spawning new processes.
threads = 2

# ── Timeouts ───────────────────────────────────────────────────────────────────
# Requests taking longer than this are killed (prevents worker starvation)
timeout = 120
# Graceful restart: finish in-flight requests before exiting
graceful_timeout = 30
# Keep idle connections alive LONGER than the load balancer's idle timeout
# (the AWS ALB uses 60s). If gunicorn closes a pooled connection first, the ALB
# can reuse one that is already going away and answer the client with a 502 that
# Django never sees — no app log, no target-5xx metric, just a failed request in
# the browser. AWS's own guidance is to keep the backend above the balancer.
# The deployed ECS command passes --keep-alive explicitly (see infra/terraform/
# ecs.tf); this keeps any other way of starting gunicorn consistent with it.
keepalive = 75

# ── Binding ────────────────────────────────────────────────────────────────────
bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"

# ── Logging ────────────────────────────────────────────────────────────────────
loglevel = os.environ.get("LOG_LEVEL", "info")
accesslog = "-"    # stdout
errorlog  = "-"    # stderr
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# ── Worker class ───────────────────────────────────────────────────────────────
# 'sync' is the safest default. Switch to 'gthread' for higher throughput
# on I/O-heavy instances (needs pip install gunicorn[gthread]).
worker_class = "sync"

# ── Preload ────────────────────────────────────────────────────────────────────
# Load the Django app once before forking workers — saves RAM on each fork
# and catches import errors before traffic is accepted.
preload_app = True
