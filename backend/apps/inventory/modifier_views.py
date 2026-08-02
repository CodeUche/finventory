"""Modifier group / option endpoints, plus what the POS needs to render them."""

from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsManagerOrSuperuser, IsStaff

from .models import Product
from .modifier_models import ModifierGroup, ModifierOption


class ModifierOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ModifierOption
        fields = ["id", "group", "name", "price_delta", "is_default", "is_active", "sort_order"]
        read_only_fields = ["id"]


class ModifierGroupSerializer(serializers.ModelSerializer):
    options = ModifierOptionSerializer(many=True, read_only=True)
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = ModifierGroup
        fields = [
            "id", "name", "description", "products", "product_count", "is_required",
            "min_choices", "max_choices", "sort_order", "is_active", "options",
        ]
        read_only_fields = ["id", "options", "product_count"]

    def get_product_count(self, obj) -> int:
        return obj.products.count()

    def validate(self, attrs):
        low = attrs.get("min_choices", getattr(self.instance, "min_choices", 0))
        high = attrs.get("max_choices", getattr(self.instance, "max_choices", 1))
        # max_choices 0 means "no limit", so only compare when a limit is set.
        if high and low > high:
            raise serializers.ValidationError(
                {"min_choices": "The minimum cannot be more than the maximum."}
            )
        return attrs


class ModifierGroupViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = ModifierGroupSerializer
    permission_classes = [IsAuthenticated, IsManagerOrSuperuser]
    filterset_fields = ["is_active", "is_required"]

    def get_queryset(self):
        return (
            ModifierGroup.objects
            .filter(organisation=self._get_organisation())
            .prefetch_related("options", "products")
        )

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated, IsStaff])
    def for_product(self, request):
        """What the till should ask when this product is added."""
        product = Product.objects.filter(
            organisation=self._get_organisation(), id=request.query_params.get("product"),
        ).first()
        if product is None:
            return Response({"error": "Product not found"}, status=404)
        from .modifier_services import ModifierService
        return Response({
            "results": ModifierGroupSerializer(
                ModifierService.groups_for(product), many=True,
            ).data
        })


class ModifierOptionViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = ModifierOptionSerializer
    permission_classes = [IsAuthenticated, IsManagerOrSuperuser]
    filterset_fields = ["group", "is_active"]

    def get_queryset(self):
        return ModifierOption.objects.filter(organisation=self._get_organisation())
