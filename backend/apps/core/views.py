"""Core utility views."""

from django.core.cache import cache
from django.db import connection
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthCheckView(APIView):
    """
    GET /api/v1/health/

    HTTP 200  — database reachable (app is serving requests).
               Cache may report "degraded" but the app still functions.
    HTTP 503  — database unreachable (app cannot serve requests).

    Redis/cache is treated as optional infrastructure: its failure degrades
    background tasks (Celery) but does not prevent API responses. Returning
    503 for a missing Redis service would break CI and load-balancer health
    checks even though the app is perfectly healthy.

    No authentication required. No throttling either: load balancers and
    uptime monitors poll this endpoint every 15-30s (120-240 req/hour),
    which blows past the default anonymous throttle (60/hour in
    production.py) and gets self-throttled to 429 — the health check would
    be reporting on its own rate limit, not the app's actual health.
    """

    permission_classes = [AllowAny]
    throttle_classes = []

    def get(self, request):
        db_status    = self._check_db()
        cache_status = self._check_cache()

        # App is "ok" only when both services are healthy.
        # DB down → 503 (hard failure). Cache down → 200 with degraded warning.
        db_ok    = db_status == "ok"
        overall  = "ok" if db_ok and cache_status == "ok" else "degraded"
        http_status = 200 if db_ok else 503

        return Response(
            {
                "status": overall,
                "database": db_status,
                "cache": cache_status,
                "version": "1.0.0",
            },
            status=http_status,
        )

    def _check_db(self) -> str:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            return "ok"
        except Exception:
            return "error"

    def _check_cache(self) -> str:
        try:
            cache.set("_health_probe", "1", timeout=5)
            result = cache.get("_health_probe")
            return "ok" if result == "1" else "error"
        except Exception:
            return "error"
