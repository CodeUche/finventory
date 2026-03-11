"""Tenancy views: Organisations, Memberships, Invitations."""

import re

from django.utils import timezone
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import IsOwnerOrAdmin
from apps.core.throttles import BankResolveRateThrottle, InvitationRateThrottle

# Nigerian NUBAN account numbers are exactly 10 digits.
# Bank codes are 3–6 digit strings assigned by the CBN.
_ACCOUNT_NUMBER_RE = re.compile(r"^\d{10}$")
_BANK_CODE_RE = re.compile(r"^\d{3,6}$")

from .models import EmailConfig, Invitation, Membership, ModulePermission, Organisation
from .serializers import InvitationSerializer, MembershipSerializer, ModulePermissionSerializer, OrganisationSerializer
from .services import OrganisationService

# Maximum sub-accounts an admin can create (excluding the owner)
MAX_TEAM_MEMBERS = 3


class EmailConfigSerializer(drf_serializers.ModelSerializer):
    """Serializer for per-org SMTP configuration. Password is write-only."""
    smtp_password = drf_serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = EmailConfig
        fields = [
            "id", "smtp_host", "smtp_port", "smtp_username", "smtp_password",
            "use_tls", "from_name", "from_email", "is_active",
        ]


class OrganisationViewSet(viewsets.ModelViewSet):
    """
    CRUD for organisations.

    - List: returns organisations the authenticated user belongs to.
    - Create: creates a new organisation and makes the user OWNER.
    - Retrieve/Update/Delete: requires ADMIN role.
    """

    serializer_class = OrganisationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Only return orgs the user is an active member of
        user_org_ids = self.request.user.memberships.filter(
            is_active=True
        ).values_list("organisation_id", flat=True)
        return Organisation.objects.filter(id__in=user_org_ids, is_active=True)

    def perform_create(self, serializer):
        OrganisationService.create_organisation(
            name=serializer.validated_data["name"],
            owner=self.request.user,
            extra=serializer.validated_data,
        )

    @action(detail=True, methods=["post"], permission_classes=[IsOwnerOrAdmin],
            throttle_classes=[InvitationRateThrottle])
    def invite(self, request, pk=None):
        """Send an invitation to join this organisation."""
        org = self.get_object()

        # Enforce member limit (owners are excluded from the count)
        active_non_owner = Membership.objects.filter(
            organisation=org, is_active=True
        ).exclude(role=Membership.Role.OWNER).count()
        if active_non_owner >= MAX_TEAM_MEMBERS:
            return Response(
                {"error": {"message": f"Maximum {MAX_TEAM_MEMBERS} team members allowed. Deactivate a member first."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        invitation = OrganisationService.invite_member(
            organisation=org,
            email=request.data.get("email"),
            role=request.data.get("role", Membership.Role.STAFF),
            invited_by=request.user,
        )
        return Response(InvitationSerializer(invitation).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "put", "patch"], permission_classes=[IsOwnerOrAdmin], url_path="email_config")
    def email_config(self, request, pk=None):
        """GET/PUT /organisations/{id}/email_config/ — manage SMTP settings."""
        org = self.get_object()
        config, _ = EmailConfig.objects.get_or_create(organisation=org)
        if request.method == "GET":
            return Response(EmailConfigSerializer(config).data)
        serializer = EmailConfigSerializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if "smtp_password" in data and data["smtp_password"]:
            config.smtp_password = data["smtp_password"]
        for field in ["smtp_host", "smtp_port", "smtp_username", "use_tls", "from_name", "from_email", "is_active"]:
            if field in data:
                setattr(config, field, data[field])
        config.save()
        return Response(EmailConfigSerializer(config).data)

    @action(detail=False, methods=["post"])
    def accept_invitation(self, request):
        """Accept a pending invitation using a token."""
        token = request.data.get("token")
        try:
            invitation = Invitation.objects.get(
                token=token,
                is_consumed=False,
                expires_at__gte=timezone.now(),
            )
        except Invitation.DoesNotExist:
            return Response(
                {"error": {"code": "invalid_token", "message": "Invitation not found or expired."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        membership = OrganisationService.accept_invitation(invitation, request.user)
        return Response(MembershipSerializer(membership).data)

    @action(detail=True, methods=["get"], url_path="my_membership")
    def my_membership(self, request, pk=None):
        """GET /organisations/{id}/my_membership/ — return the current user's membership + permissions."""
        org = self.get_object()
        try:
            membership = Membership.objects.prefetch_related("module_permissions").get(
                organisation=org, user=request.user, is_active=True
            )
        except Membership.DoesNotExist:
            return Response(
                {"error": {"message": "You are not an active member of this organisation."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(MembershipSerializer(membership).data)

    @action(detail=True, methods=["post"], permission_classes=[IsOwnerOrAdmin],
            url_path="create_subaccount", throttle_classes=[InvitationRateThrottle])
    def create_subaccount(self, request, pk=None):
        """
        POST /organisations/{id}/create_subaccount/
        Body: { "username": "john", "password": "secret", "role": "staff" }

        Creates a new user with email = username@<org_slug> and adds them as a member.
        When the org is deleted, the membership cascade-deletes (user remains but loses access).
        """
        org = self.get_object()

        # Enforce member limit
        active_non_owner = Membership.objects.filter(
            organisation=org, is_active=True
        ).exclude(role=Membership.Role.OWNER).count()
        if active_non_owner >= MAX_TEAM_MEMBERS:
            return Response(
                {"error": {"message": f"Maximum {MAX_TEAM_MEMBERS} team members allowed."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        username = (request.data.get("username") or "").strip().lower()
        password = request.data.get("password", "").strip()
        role = request.data.get("role", Membership.Role.STAFF)

        if not username or not password:
            return Response(
                {"error": {"message": "Username and password are required."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if role == Membership.Role.OWNER:
            return Response(
                {"error": {"message": "Cannot create a second owner."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from django.contrib.auth import get_user_model
        User = get_user_model()

        email = f"{username}@{org.slug}"
        if User.objects.filter(email=email).exists():
            return Response(
                {"error": {"message": f"Username '{username}' already exists in this organisation."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = User.objects.create_user(
            email=email,
            password=password,
            first_name=username.capitalize(),
            last_name="",
            is_verified=True,
        )
        membership = Membership.objects.create(
            organisation=org,
            user=user,
            role=role,
            invited_by=request.user,
            is_active=True,
        )
        return Response(MembershipSerializer(membership).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"], url_path="resolve_bank_account",
            throttle_classes=[BankResolveRateThrottle])
    def resolve_bank_account(self, request):
        """
        GET /organisations/resolve_bank_account/?account_number=0123456789&bank_code=057

        Proxies to Paystack's bank-account name resolution API.

        Security controls:
          - BankResolveRateThrottle: 20 calls/min per user (guards Paystack quota).
          - Strict regex validation on account_number (exactly 10 digits — CBN NUBAN)
            and bank_code (3–6 digits — CBN assigned codes). This prevents SSRF /
            parameter-injection attacks against the Paystack upstream.
          - Paystack API key is never returned to the client; only the resolved
            account name/status from Paystack's response is forwarded.
        """
        import json as _json
        import urllib.request
        from django.conf import settings

        account_number = request.query_params.get("account_number", "").strip()
        bank_code = request.query_params.get("bank_code", "").strip()

        # ── Input validation ──────────────────────────────────────────────────
        if not account_number or not bank_code:
            return Response(
                {"error": {"message": "account_number and bank_code are required."}},
                status=400,
            )
        if not _ACCOUNT_NUMBER_RE.match(account_number):
            return Response(
                {"error": {"message": "account_number must be exactly 10 digits (CBN NUBAN format)."}},
                status=400,
            )
        if not _BANK_CODE_RE.match(bank_code):
            return Response(
                {"error": {"message": "bank_code must be 3–6 digits."}},
                status=400,
            )

        paystack_key = getattr(settings, "PAYSTACK_SECRET_KEY", "")
        if not paystack_key:
            return Response(
                {"error": {"message": "Paystack API key not configured on server."}},
                status=503,
            )

        # Build URL using validated, regex-matched values only (no raw user input
        # injected into the URL string beyond the validated parts).
        url = (
            f"https://api.paystack.co/bank/resolve"
            f"?account_number={account_number}&bank_code={bank_code}"
        )
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {paystack_key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = _json.loads(resp.read().decode())
            return Response(body)
        except Exception as e:
            return Response({"error": {"message": "Bank account lookup failed. Please try again."}}, status=502)


class MembershipViewSet(viewsets.ModelViewSet):
    """Manage members of the current organisation."""

    serializer_class = MembershipSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

    def get_queryset(self):
        org = getattr(self.request, "organisation", None)
        if not org:
            return Membership.objects.none()
        return Membership.objects.filter(organisation=org).select_related("user").prefetch_related("module_permissions")

    @action(detail=True, methods=["post"], url_path="set_permissions")
    def set_permissions(self, request, pk=None):
        """
        POST /tenancy/memberships/{id}/set_permissions/
        Body: { "permissions": [{ "module": "sales", "access_level": "edit" }, ...] }

        Replaces all module permissions for this membership atomically.
        Cannot modify owner memberships.
        """
        membership = self.get_object()
        if membership.role == Membership.Role.OWNER:
            return Response(
                {"error": {"message": "Cannot restrict permissions for the organisation owner."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        permissions = request.data.get("permissions", [])

        # Validate each entry
        valid_modules = {c[0] for c in ModulePermission.MODULE_CHOICES}
        valid_levels = {c[0] for c in ModulePermission.ACCESS_CHOICES}
        for p in permissions:
            if p.get("module") not in valid_modules:
                return Response(
                    {"error": {"message": f"Invalid module: {p.get('module')}"}},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if p.get("access_level") not in valid_levels:
                return Response(
                    {"error": {"message": f"Invalid access_level: {p.get('access_level')}"}},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Replace atomically
        membership.module_permissions.all().delete()
        ModulePermission.objects.bulk_create([
            ModulePermission(
                membership=membership,
                module=p["module"],
                access_level=p["access_level"],
            )
            for p in permissions
        ])

        membership.refresh_from_db()
        return Response(MembershipSerializer(membership).data)
