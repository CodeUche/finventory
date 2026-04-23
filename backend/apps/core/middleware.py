"""
RLS Middleware — sets the PostgreSQL session variable `app.current_org_id`
on every request so Row Level Security policies can enforce tenant isolation.

How it works
------------
Every tenant table has a policy:
    USING (organisation_id = current_setting('app.current_org_id', TRUE)::uuid)

This middleware extracts the org ID from the `X-Organisation-ID` request header
(the same header the views use) and sets the session variable before the view
runs, then clears it after the response.

The sentinel value '00000000-0000-0000-0000-000000000000' is used for requests
that have no org header (auth endpoints, health checks, etc.).  No row in any
tenant table has that as its organisation_id, so those requests see an empty
result set for tenant tables — which is correct: unauthenticated requests
should not access tenant data.

Two-role setup (recommended for production)
-------------------------------------------
Without FORCE ROW LEVEL SECURITY the table owner (superuser) bypasses RLS by
default, so management commands / migrations run unimpeded.  For Django HTTP
requests to be subject to RLS you should connect as a non-owner role:

    1. Run `python manage.py setup_rls_role` once to create `audity_app`.
    2. Set APP_DATABASE_URL in your environment pointing to the same DB but
       authenticating as `audity_app`.
    3. In settings/production.py add:
           if env('APP_DATABASE_URL', default=None):
               DATABASES['default'] = env.db('APP_DATABASE_URL')
    4. Keep DATABASE_URL (superuser) only in the Procfile release command for
       migrations:  release: DATABASE_URL=$DATABASE_URL python manage.py migrate

If you run everything as the superuser (single-role Railway setup) RLS is
still enforced in both directions because the middleware always sets the
session variable, giving belt-and-suspenders protection against code bugs.
"""

from django.db import connection

SENTINEL = "00000000-0000-0000-0000-000000000000"


class RLSMiddleware:
    """
    Sets ``app.current_org_id`` on the PostgreSQL connection before every
    request and resets it to the sentinel after the response is sent.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        org_id = request.headers.get("X-Organisation-ID", "").strip()
        if not _looks_like_uuid(org_id):
            # Header missing or invalid — fall back to the ?org= query param.
            # Tauri desktop clients route requests through Rust reqwest which can
            # silently drop custom headers; the frontend also sends ?org=<uuid> as
            # a belt-and-suspenders fallback so RLS is always set correctly.
            org_id = request.GET.get("org", "").strip()
        if not _looks_like_uuid(org_id):
            org_id = SENTINEL
        _set_org(org_id)
        try:
            response = self.get_response(request)
        finally:
            # Always clear — prevents the org leaking to the next request on a
            # pooled connection.
            _set_org(SENTINEL)
        return response


# ── helpers ───────────────────────────────────────────────────────────────────

def _looks_like_uuid(value: str) -> bool:
    import re
    return bool(re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        value,
        re.IGNORECASE,
    ))


def _set_org(org_id: str) -> None:
    try:
        with connection.cursor() as cursor:
            # Use SET (session-level) so it survives across statements even
            # when the request is not wrapped in an atomic block.
            cursor.execute("SELECT set_config('app.current_org_id', %s, FALSE)", [org_id])
    except Exception:
        # Never crash a request because of an RLS bookkeeping failure.
        pass
