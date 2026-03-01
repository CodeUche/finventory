"""
ViewSet mixins that enforce tenant isolation automatically.

Usage:
    class ProductViewSet(TenantFilterMixin, ModelViewSet):
        ...

All queries are automatically scoped to request.organisation.
This prevents IDOR by making cross-tenant access structurally impossible.

Note on JWT + Middleware order:
    TenantFilterMixin.get_queryset() is called AFTER DRF authentication,
    so request.user is already the JWT-authenticated user here.
    We call resolve_organisation() (phase 2 of tenant resolution) here.
"""

import logging

from apps.core.exceptions import TenantViolationError

logger = logging.getLogger(__name__)


class TenantFilterMixin:
    """
    Mixin that scopes all queries to the current organisation.

    Override `tenant_field` if the model uses a different FK name.
    """

    tenant_field: str = "organisation"

    def _get_organisation(self):
        """
        Resolve (and cache) the organisation for this request.

        Phase 2 of tenant resolution — runs after DRF authentication.
        """
        if getattr(self.request, "organisation", None) is not None:
            return self.request.organisation

        from apps.tenancy.middleware import resolve_organisation
        org = resolve_organisation(self.request)

        if org is None:
            logger.error(
                "TenantFilterMixin: could not resolve organisation for user %s",
                getattr(self.request.user, "id", "anonymous"),
            )
            raise TenantViolationError(
                "Organisation context is missing or you do not have access. "
                "Pass the X-Organisation-ID header."
            )
        return org

    def get_queryset(self):
        org = self._get_organisation()
        qs = super().get_queryset()
        return qs.filter(**{self.tenant_field: org})

    def perform_create(self, serializer):
        """Automatically inject organisation on create."""
        org = self._get_organisation()
        serializer.save(**{self.tenant_field: org})

    def perform_update(self, serializer):
        serializer.save()


class AuditMixin:
    """Injects created_by / updated_by on write operations."""

    def perform_create(self, serializer):
        serializer.save()

    def perform_update(self, serializer):
        serializer.save()
