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

from apps.core.validators import validate_image_upload

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
    """
    User registration serializer with strong input validation.

    Security controls:
      - Password min_length=10 enforced at field level.
      - Django AUTH_PASSWORD_VALIDATORS applied (similarity, common passwords,
        numeric-only, minimum length — all configured in settings).
      - Email normalised to lowercase to prevent duplicate-account creation
        via case variation (e.g. User@Example.com vs user@example.com).
      - Name fields capped to 150 chars (AbstractUser default max_length).
      - Phone capped to 30 chars; only digits, spaces and + allowed.
    """

    password = serializers.CharField(
        write_only=True, min_length=10, max_length=128,
        style={"input_type": "password"},
    )
    password_confirm = serializers.CharField(
        write_only=True, max_length=128,
        style={"input_type": "password"},
    )

    class Meta:
        model = User
        fields = ["email", "first_name", "last_name", "phone", "password", "password_confirm"]
        extra_kwargs = {
            "first_name": {"max_length": 150, "required": False, "allow_blank": True},
            "last_name": {"max_length": 150, "required": False, "allow_blank": True},
            "phone": {"max_length": 30, "required": False, "allow_blank": True},
        }

    def validate_email(self, value):
        # Normalise email to lowercase to prevent case-variant duplicates
        return value.strip().lower()

    def validate_phone(self, value):
        import re
        # Allow digits, spaces, hyphens, parentheses, and leading +
        if value and not re.match(r"^[+\d\s\-\(\)]{0,30}$", value):
            raise serializers.ValidationError(
                "Phone number may only contain digits, spaces, +, -, and parentheses."
            )
        return value

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
        extra_kwargs = {
            "first_name": {"max_length": 150, "required": False, "allow_blank": True},
            "last_name": {"max_length": 150, "required": False, "allow_blank": True},
            "phone": {"max_length": 30, "required": False, "allow_blank": True},
            # Only allow safe image formats for avatar uploads
            "avatar": {"validators": [validate_image_upload], "required": False},
        }


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=10)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        return attrs
