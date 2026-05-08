"""
Authentication serializers.

CustomTokenObtainPairSerializer enriches JWT tokens with
tenant + role information so downstream services don't need
separate membership lookups for common operations.
"""

import logging

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password as _validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from apps.core.validators import validate_image_upload

logger = logging.getLogger(__name__)
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
        token["is_sub_account"] = user.is_sub_account

        # Embed memberships (org_id → role) for fast client-side routing.
        # Use raw SQL inside atomic() so set_config and SELECT are in the same
        # PostgreSQL transaction — set_config(..., TRUE) (transaction-local) is
        # then visible to the membership query under SENTINEL regardless of whether
        # a separate _set_user() call worked and regardless of pgBouncer mode.
        memberships = {}
        try:
            from django.db import connection as _mc, transaction as _mt
            with _mt.atomic():
                with _mc.cursor() as _cur:
                    # Layer 1: attempt to disable RLS entirely for this transaction.
                    # Requires the BYPASSRLS attribute or superuser privilege.
                    # We wrap it in a SAVEPOINT so a permission-denied error does
                    # not abort the outer transaction — we fall back to the SENTINEL
                    # GUC pattern instead.
                    _rls_bypassed = False
                    try:
                        _cur.execute("SAVEPOINT audity_token_rls")
                        _cur.execute("SET LOCAL row_security = OFF")
                        _cur.execute("RELEASE SAVEPOINT audity_token_rls")
                        _rls_bypassed = True
                    except Exception as _rls_err:
                        _cur.execute("ROLLBACK TO SAVEPOINT audity_token_rls")
                        # Layer 2: SENTINEL GUC pattern — the membership_select
                        # RLS policy allows reads when current_org_id = SENTINEL
                        # AND current_user_id = user.pk (both transaction-local).
                        _cur.execute(
                            "SELECT set_config('app.current_org_id', '00000000-0000-0000-0000-000000000000', TRUE)"
                        )
                        _cur.execute(
                            "SELECT set_config('app.current_user_id', %s, TRUE)",
                            [str(user.pk)],
                        )
                        logger.debug(
                            "get_token: BYPASSRLS unavailable (%s), using SENTINEL GUC",
                            type(_rls_err).__name__,
                        )

                    _cur.execute(
                        "SELECT organisation_id, role FROM tenancy_membership"
                        " WHERE user_id = %s AND is_active = TRUE",
                        [str(user.pk)],
                    )
                    rows = _cur.fetchall()
                    memberships = {str(r[0]): r[1] for r in rows}
                    logger.info(
                        "get_token: user=%s memberships=%d rls_bypassed=%s",
                        user.pk, len(rows), _rls_bypassed,
                    )
        except Exception as exc:
            logger.error(
                "get_token: raw-SQL membership query FAILED for user=%s: %s: %s",
                user.pk, type(exc).__name__, exc,
            )
            # Layer 3: ORM fallback — works on SQLite (tests) and when the raw
            # SQL path is unavailable for any reason.
            try:
                from apps.tenancy.models import Membership as _M
                memberships = {
                    str(m.organisation_id): m.role
                    for m in _M.objects.filter(user=user, is_active=True)
                }
                logger.info(
                    "get_token: ORM fallback found %d membership(s) for user=%s",
                    len(memberships), user.pk,
                )
            except Exception as orm_exc:
                logger.error(
                    "get_token: ORM fallback also failed for user=%s: %s",
                    user.pk, orm_exc,
                )
        if not memberships:
            logger.warning(
                "get_token: JWT will have EMPTY memberships for user=%s — "
                "user will be routed to /onboarding if org fetch also fails",
                user.pk,
            )
        token["memberships"] = memberships
        token["token_version"] = user.token_version
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
        value = value.strip().lower()
        # Uniqueness is enforced at the view level (with a friendly message) but
        # we also guard here so direct API calls get a proper 400, not a 500.
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError(
                "An account with this email address already exists."
            )
        return value

    def validate_phone(self, value):
        import re
        # Allow digits, spaces, hyphens, parentheses, and leading +
        if value and not re.match(r"^[+\d\s\-\(\)]{0,30}$", value):
            raise serializers.ValidationError(
                "Phone number may only contain digits, spaces, +, -, and parentheses."
            )
        # Enforce phone uniqueness — generic message to prevent enumeration
        if value and User.objects.filter(phone=value).exists():
            raise serializers.ValidationError(
                "This information is already in use."
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

    has_partner_profile = serializers.SerializerMethodField()

    def get_has_partner_profile(self, obj):
        return hasattr(obj, 'partner_profile') and obj.partner_profile.is_active

    class Meta:
        model = User
        fields = [
            "id", "email", "first_name", "last_name", "phone",
            "avatar", "is_verified", "is_superuser", "is_staff", "is_sub_account",
            "must_change_password", "mfa_enabled",
            "has_partner_profile", "created_at",
        ]
        read_only_fields = ["id", "email", "is_verified", "is_superuser", "is_staff", "is_sub_account", "must_change_password", "mfa_enabled", "has_partner_profile", "created_at"]
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
