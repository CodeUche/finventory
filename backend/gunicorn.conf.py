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
# Keep idle connections alive for 5 s (reduces TCP overhead for API clients)
keepalive = 5

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
