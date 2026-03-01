"""Core utility views."""

from django.db import connection
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthCheckView(APIView):
    """
    GET /api/v1/health/

    Returns 200 if the application and database are reachable.
    Used by load balancers and monitoring systems.
    No authentication required.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        # Verify database connectivity
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            db_status = "ok"
        except Exception:
            db_status = "error"

        return Response(
            {
                "status": "ok" if db_status == "ok" else "degraded",
                "database": db_status,
                "version": "1.0.0",
            }
        )
