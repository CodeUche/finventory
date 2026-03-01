import django_filters
from rest_framework.permissions import IsAuthenticated

from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsStaff
from rest_framework import viewsets

from .models import Customer
from .serializers import CustomerSerializer


class CustomerFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr="icontains")
    customer_type = django_filters.ChoiceFilter(choices=Customer.CustomerType.choices)
    is_active = django_filters.BooleanFilter()

    class Meta:
        model = Customer
        fields = ["name", "customer_type", "is_active"]


class CustomerViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    permission_classes = [IsAuthenticated, IsStaff]
    filterset_class = CustomerFilter
    search_fields = ["name", "code", "email", "phone"]
    ordering_fields = ["name", "outstanding_balance", "created_at"]
