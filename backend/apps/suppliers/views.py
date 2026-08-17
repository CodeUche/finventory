from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsStaff, plan_requires
from apps.core.permissions import requires_module
# The owner's per-person ticks, enforced server-side (H-2). Mirrors
# useModuleAccess.ts: owners and admins bypass; for everyone else no
# record means no access, and only what was granted is granted.
_ModAccess_suppliers = requires_module("suppliers")


_PlanSuppliers = plan_requires('suppliers')
from .models import Supplier
from .serializers import SupplierSerializer


class SupplierViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    queryset = Supplier.objects.filter(is_active=True)
    serializer_class = SupplierSerializer
    permission_classes = [IsAuthenticated, IsStaff, _PlanSuppliers, _ModAccess_suppliers]
    search_fields = ["name", "code", "email", "phone"]
    ordering_fields = ["name", "created_at"]
