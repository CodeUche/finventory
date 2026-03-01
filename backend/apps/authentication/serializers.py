"""
Authentication serializers.

CustomTokenObtainPairSerializer enriches JWT tokens with
tenant + role information so downstream services don't need
separate membership lookups for common operations.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password as _validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Adds user_id, email, and memberships to the JWT payload.

    Encoding org/role in the token avoids a DB lookup per request
    for the common case of single-org users.
    """

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["email"] = user.email
        token["full_name"] = user.get_full_name()
        token["is_verified"] = user.is_verified

        # Embed memberships (org_id → role) for fast client-side routing
        memberships = {
            str(m.organisation_id): m.role
            for m in user.memberships.filter(is_active=True).select_related("organisation")
        }
        token["memberships"] = memberships
        return token


class RegisterSerializer(serializers.ModelSerializer):
    """User registration serializer with strong password validation."""

    password = serializers.CharField(write_only=True, min_length=10, style={"input_type": "password"})
    password_confirm = serializers.CharField(write_only=True, style={"input_type": "password"})

    class Meta:
        model = User
        fields = ["email", "first_name", "last_name", "phone", "password", "password_confirm"]

    def validate(self, attrs):
        if attrs["password"] != attrs.pop("password_confirm"):
            raise serializers.ValidationError({"password_confirm": "Passwords do not match."})
        # Enforce AUTH_PASSWORD_VALIDATORS (length, common passwords, numeric-only, etc.)
        try:
            _validate_password(attrs["password"])
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)})
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class UserProfileSerializer(serializers.ModelSerializer):
    """Read/update current user profile."""

    class Meta:
        model = User
        fields = [
            "id", "email", "first_name", "last_name", "phone",
            "avatar", "is_verified", "is_superuser", "is_staff", "created_at",
        ]
        read_only_fields = ["id", "email", "is_verified", "is_superuser", "is_staff", "created_at"]


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=10)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        return attrs
