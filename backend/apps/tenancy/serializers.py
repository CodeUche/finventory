"""Tenancy serializers."""

from rest_framework import serializers

from .models import Invitation, Membership, Organisation


class OrganisationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organisation
        fields = [
            "id", "name", "slug", "account_type", "registration_number",
            "tax_id", "country", "currency", "phone", "email", "address",
            "logo", "is_active", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "slug", "created_at", "updated_at"]

    def validate_name(self, value):
        if len(value.strip()) < 2:
            raise serializers.ValidationError("Organisation name must be at least 2 characters.")
        return value.strip()


class MembershipSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_full_name = serializers.CharField(source="user.get_full_name", read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "user", "user_email", "user_full_name", "role", "is_active", "joined_at"]
        read_only_fields = ["id", "user", "joined_at"]


class InvitationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invitation
        fields = ["id", "email", "role", "is_consumed", "expires_at", "created_at"]
        read_only_fields = ["id", "token", "is_consumed", "created_at"]
