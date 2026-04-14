from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsStaff, plan_requires

_PlanSuppliers = plan_requires('suppliers')
from .models import Supplier
from .serializers import SupplierSerializer


class SupplierViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    queryset = Supplier.objects.filter(is_active=True)
    serializer_class = SupplierSerializer
    permission_classes = [IsAuthenticated, IsStaff, _PlanSuppliers]
    search_fields = ["name", "code", "email", "phone"]
    ordering_fields = ["name", "created_at"]
