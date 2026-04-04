"""Core utility views."""

from django.core.cache import cache
from django.db import connection
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthCheckView(APIView):
    """
    GET /api/v1/health/

    Returns 200 if the application, database, and cache are reachable.
    Used by load balancers, monitoring systems, and CI health checks.
    No authentication required.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        db_status = self._check_db()
        cache_status = self._check_cache()

        overall = "ok" if db_status == "ok" and cache_status == "ok" else "degraded"

        return Response(
            {
                "status": overall,
                "database": db_status,
                "cache": cache_status,
                "version": "1.0.0",
            },
            status=200 if overall == "ok" else 503,
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
