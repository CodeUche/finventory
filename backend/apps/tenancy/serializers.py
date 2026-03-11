"""Tenancy serializers."""

import re

from rest_framework import serializers

from apps.core.validators import validate_image_upload

from .models import Invitation, Membership, ModulePermission, Organisation


class OrganisationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organisation
        fields = [
            "id", "name", "slug", "account_type", "registration_number",
            "tax_id", "country", "currency", "phone", "email", "address",
            "logo", "letterhead", "is_active", "created_at", "updated_at",
            "bank_name", "bank_account_number", "bank_account_name", "bank_sort_code",
        ]
        read_only_fields = ["id", "slug", "created_at", "updated_at"]
        extra_kwargs = {
            # Enforce upload validators so only safe image formats reach the server
            "logo": {"validators": [validate_image_upload], "required": False},
            "letterhead": {"validators": [validate_image_upload], "required": False},
            # Field length caps matching model definitions
            "registration_number": {"max_length": 100, "required": False, "allow_blank": True},
            "tax_id": {"max_length": 50, "required": False, "allow_blank": True},
            "phone": {"max_length": 30, "required": False, "allow_blank": True},
            "address": {"max_length": 500, "required": False, "allow_blank": True},
            "bank_name": {"max_length": 200, "required": False, "allow_blank": True},
            "bank_account_name": {"max_length": 200, "required": False, "allow_blank": True},
            "bank_sort_code": {"max_length": 20, "required": False, "allow_blank": True},
        }

    def validate_name(self, value):
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("Organisation name must be at least 2 characters.")
        return value

    def validate_bank_account_number(self, value):
        """Nigerian NUBAN account numbers must be exactly 10 digits."""
        if value and not re.match(r"^\d{10}$", value):
            raise serializers.ValidationError(
                "Bank account number must be exactly 10 digits (CBN NUBAN format)."
            )
        return value

    def validate_phone(self, value):
        if value and not re.match(r"^[+\d\s\-\(\)]{0,30}$", value):
            raise serializers.ValidationError(
                "Phone number may only contain digits, spaces, +, -, and parentheses."
            )
        return value


class ModulePermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ModulePermission
        fields = ["id", "module", "access_level"]


class MembershipSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_full_name = serializers.CharField(source="user.get_full_name", read_only=True)
    module_permissions = ModulePermissionSerializer(many=True, read_only=True)

    class Meta:
        model = Membership
        fields = [
            "id", "user", "user_email", "user_full_name", "role",
            "is_active", "joined_at", "module_permissions",
        ]
        read_only_fields = ["id", "user", "joined_at"]


class InvitationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invitation
        fields = ["id", "email", "role", "is_consumed", "expires_at", "created_at"]
        read_only_fields = ["id", "token", "is_consumed", "created_at"]
