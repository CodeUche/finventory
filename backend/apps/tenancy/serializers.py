"""Tenancy serializers."""

import re

from rest_framework import serializers

from apps.core.validators import validate_image_upload

from .models import Invitation, Membership, ModulePermission, Organisation


class OrganisationSerializer(serializers.ModelSerializer):
    managing_firm_name = serializers.SerializerMethodField()
    managing_firm_logo = serializers.SerializerMethodField()
    child_entity_count = serializers.SerializerMethodField()

    def get_child_entity_count(self, obj):
        return obj.child_entities.filter(is_active=True, is_deleted=False).count()

    def get_managing_firm_name(self, obj):
        """Return the partner firm name if this org has an active partner managing it."""
        link = obj.partner_managers.filter(is_active=True).select_related("partner").first()
        if link:
            return link.partner.firm_name or link.partner.user.email
        return None

    def get_managing_firm_logo(self, obj):
        """Return the partner firm logo URL if available."""
        link = obj.partner_managers.filter(is_active=True).select_related("partner").first()
        if link and link.partner.firm_logo:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(link.partner.firm_logo.url)
        return None

    class Meta:
        model = Organisation
        fields = [
            "id", "name", "slug", "account_type", "registration_number",
            "tax_id", "country", "currency", "phone", "email", "address",
            "logo", "company_stamp", "is_active", "created_at", "updated_at",
            "bank_name", "bank_account_number", "bank_account_name", "bank_sort_code",
            "brand_color",
            "invoice_company_name", "company_name_font",
            "company_name_font_color", "company_name_font_size",
            "company_name_font_bold", "company_name_font_italic", "company_name_font_underline",
            "show_company_name_on_pdf",
            "invoice_template", "pension_provider", "ai_custom_context",
            "onboarding_completed",
            "managing_firm_name", "managing_firm_logo",
            "parent_org", "entity_group_name", "child_entity_count",
        ]
        read_only_fields = ["id", "slug", "created_at", "updated_at", "managing_firm_name", "managing_firm_logo", "child_entity_count"]
        extra_kwargs = {
            # Enforce upload validators so only safe image formats reach the server
            "logo": {"validators": [validate_image_upload], "required": False},
            "company_stamp": {"validators": [validate_image_upload], "required": False},
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
    partner_firm_name = serializers.SerializerMethodField()

    def get_partner_firm_name(self, obj):
        """Return the partner firm name if this member is a linked accountant partner."""
        try:
            profile = obj.user.partner_profile
            # Confirm there's an active link between this partner and this org
            if profile.clients.filter(organisation=obj.organisation, is_active=True).exists():
                return profile.firm_name or obj.user.email
        except Exception:
            pass
        return None

    class Meta:
        model = Membership
        fields = [
            "id", "user", "user_email", "user_full_name", "role",
            "is_active", "joined_at", "module_permissions", "partner_firm_name",
        ]
        read_only_fields = ["id", "user", "joined_at", "partner_firm_name"]


class InvitationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invitation
        fields = ["id", "email", "role", "is_consumed", "expires_at", "created_at"]
        read_only_fields = ["id", "token", "is_consumed", "created_at"]


class PartnerProfileSerializer(serializers.ModelSerializer):
    active_client_count = serializers.IntegerField(read_only=True)
    can_add_client = serializers.BooleanField(read_only=True)
    user_email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        from apps.tenancy.models import PartnerProfile
        model = PartnerProfile
        fields = [
            "id", "user_email", "tier", "firm_name", "firm_logo",
            "max_clients", "commission_rate", "total_commission_earned",
            "white_label_reports", "consolidated_reporting", "is_active",
            "referral_code", "active_client_count", "can_add_client", "created_at",
        ]
        read_only_fields = [
            "id", "user_email", "max_clients", "commission_rate",
            "total_commission_earned", "referral_code", "active_client_count", "can_add_client", "created_at",
        ]


class PartnerClientLinkSerializer(serializers.ModelSerializer):
    org_name = serializers.CharField(source="organisation.name", read_only=True)
    org_currency = serializers.CharField(source="organisation.currency", read_only=True)

    class Meta:
        from apps.tenancy.models import PartnerClientLink
        model = PartnerClientLink
        fields = [
            "id", "organisation", "org_name", "org_currency",
            "is_referred", "commission_earned", "notes", "is_active", "linked_at",
        ]
        read_only_fields = ["id", "org_name", "org_currency", "commission_earned", "linked_at"]
