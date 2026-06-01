"""
Railway release-phase migration runner.

Parses DATABASE_URL (postgres superuser) and injects its credentials as
individual DB_* env vars before calling manage.py migrate. This is needed
because the app's DB user (audity_app) lacks DDL permissions (CREATE TABLE,
ALTER TABLE) required for migrations on PostgreSQL 15+.

The web process continues to use APP_DATABASE_URL / individual DB_* vars
(audity_app with RLS), so this superuser usage is migration-only.
"""
import os
import subprocess
import sys
import urllib.parse

db_url = os.environ.get("DATABASE_URL", "")
if db_url:
    parsed = urllib.parse.urlparse(db_url)
    os.environ.update({
        "DB_USER":     parsed.username or "",
        "DB_PASSWORD": parsed.password or "",
        "DB_HOST":     parsed.hostname or "localhost",
        "DB_PORT":     str(parsed.port or 5432),
        "DB_NAME":     parsed.path.lstrip("/"),
    })
    # Prevent production.py from overriding DB config with the limited audity_app
    # user — migrations must run as the postgres superuser (from DATABASE_URL).
    os.environ.pop("APP_DATABASE_URL", None)

    # PostgreSQL 15 removed CREATE from the default PUBLIC grant on the public
    # schema. Ensure the migration user can CREATE objects before Django runs.
    try:
        import psycopg2
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("GRANT CREATE ON SCHEMA public TO CURRENT_USER;")
        conn.close()
        print("migrate.py: GRANT CREATE ON SCHEMA public succeeded.", flush=True)
    except Exception as exc:
        print(f"migrate.py: schema grant warning: {exc}", file=sys.stderr, flush=True)

result = subprocess.run(
    [sys.executable, "manage.py", "migrate", "--noinput"],
    check=False,
)
sys.exit(result.returncode)
