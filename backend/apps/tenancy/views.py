"""Tenancy views: Organisations, Memberships, Invitations."""

import logging
import re

from django.utils import timezone
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

logger = logging.getLogger(__name__)

from apps.core.permissions import IsOwnerOrAdmin
from apps.core.throttles import BankResolveRateThrottle, InvitationRateThrottle

# Nigerian NUBAN account numbers are exactly 10 digits.
# Bank codes are 3–6 digit strings assigned by the CBN.
_ACCOUNT_NUMBER_RE = re.compile(r"^\d{10}$")
_BANK_CODE_RE = re.compile(r"^\d{3,6}$")

from .models import EmailConfig, Invitation, Membership, ModulePermission, Organisation
from .serializers import InvitationSerializer, MembershipSerializer, ModulePermissionSerializer, OrganisationSerializer
from .services import OrganisationService

# Default maximum when no subscription plan is attached
_DEFAULT_MAX_TEAM_MEMBERS = 3


def _get_max_team_members(org) -> int:
    """
    Return the maximum number of non-owner team members allowed for this org,
    read from the org's subscription plan features (key: 'max_users').

    Falls back to _DEFAULT_MAX_TEAM_MEMBERS if no subscription / plan exists.
    """
    try:
        sub = getattr(org, "subscription", None)
        if sub and sub.plan:
            val = sub.plan.features.get("max_users")
            if val is not None:
                return int(val)
    except Exception:
        pass
    return _DEFAULT_MAX_TEAM_MEMBERS


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
        # Set user identity FIRST so the membership_select RLS SENTINEL branch
        # (user_id = app.current_user_id) can fire before any membership query.
        try:
            from apps.core.middleware import _set_user
            _set_user(str(self.request.user.pk))
        except Exception:
            pass

        # Pre-seed app.current_org_id from the raw request header/param BEFORE any
        # membership or org query.  RLS policies on tenancy_membership and
        # tenancy_organisation check this session variable; leaving it at the
        # SENTINEL value blocks all reads even after _set_user() is called.
        raw_org_id = getattr(self.request, '_raw_org_id', None)
        if raw_org_id:
            try:
                from apps.core.middleware import _set_org
                _set_org(str(raw_org_id))
            except Exception:
                pass

        if self.request.user.is_superuser:
            return Organisation.objects.filter(is_active=True)

        # Prefer ORM over raw SQL here — the ORM runs through Django's connection
        # which respects the set_config() calls above, and avoids UUID hex-format
        # mismatches that can cause raw SQL to return empty rows on some backends.
        user_org_ids = list(
            self.request.user.memberships
            .filter(is_active=True)
            .values_list("organisation_id", flat=True)
        )
        user_org_ids = [str(i) for i in user_org_ids]

        # Raw SQL fallback — runs when ORM returned nothing (RLS blocked it).
        # set_config and SELECT are in the same atomic() transaction so the
        # transaction-local user identity (TRUE) is visible to the query even
        # when _set_user() failed earlier and even under pgBouncer transaction mode.
        if not user_org_ids:
            from django.db import connection as _conn, transaction as _tx
            try:
                with _tx.atomic():
                    with _conn.cursor() as cur:
                        # Both GUCs must be set in the same transaction so the
                        # RLS SENTINEL branch fires on fresh pgBouncer connections.
                        cur.execute(
                            "SELECT set_config('app.current_org_id', '00000000-0000-0000-0000-000000000000', TRUE)"
                        )
                        cur.execute(
                            "SELECT set_config('app.current_user_id', %s, TRUE)",
                            [str(self.request.user.pk)],
                        )
                        cur.execute(
                            "SELECT organisation_id FROM tenancy_membership"
                            " WHERE user_id = %s AND is_active = TRUE",
                            [str(self.request.user.pk)],
                        )
                        rows = cur.fetchall()
                        user_org_ids = [str(row[0]) for row in rows]
                        logger.warning(
                            "get_queryset raw-SQL fallback: user=%s found %d org(s): %s",
                            self.request.user.pk, len(rows), user_org_ids,
                        )
            except Exception as exc:
                logger.error(
                    "get_queryset raw-SQL fallback FAILED for user=%s: %s: %s",
                    self.request.user.pk, type(exc).__name__, exc,
                )

        if user_org_ids:
            try:
                from apps.core.middleware import _set_org
                _set_org(str(user_org_ids[0]))
            except Exception:
                pass
        return Organisation.objects.filter(id__in=user_org_ids, is_active=True)

    def create(self, request, *args, **kwargs):
        if getattr(request.user, 'is_sub_account', False):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Sub-accounts cannot create organisations. Contact your administrator.")
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            org = OrganisationService.create_organisation(
                name=serializer.validated_data["name"],
                owner=request.user,
                extra=serializer.validated_data,
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error("create_organisation failed: %s", exc)
            return Response(
                {"error": {"message": f"Failed to create organisation: {exc}"}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        out = self.get_serializer(org)
        return Response(out.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], permission_classes=[IsOwnerOrAdmin],
            throttle_classes=[InvitationRateThrottle])
    def invite(self, request, pk=None):
        """Send an invitation to join this organisation."""
        org = self.get_object()

        # Enforce member limit (owners are excluded from the count; superusers bypass)
        if not request.user.is_superuser:
            max_members = _get_max_team_members(org)
            active_non_owner = Membership.objects.filter(
                organisation=org, is_active=True
            ).exclude(role=Membership.Role.OWNER).count()
            if active_non_owner >= max_members:
                return Response(
                    {"error": {"message": f"Maximum {max_members} team members allowed on your current plan. Upgrade or deactivate a member first."}},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        email = (request.data.get("email") or "").strip().lower()
        role = request.data.get("role", Membership.Role.STAFF)

        # Validate role against known choices
        valid_roles = {r[0] for r in Membership.Role.choices}
        if role not in valid_roles:
            return Response({"error": {"message": "Invalid role."}}, status=status.HTTP_400_BAD_REQUEST)

        # Sanitise module_permissions — only allow known module keys and access levels
        _valid_modules = {m[0] for m in ModulePermission.MODULE_CHOICES}
        _valid_levels = {a[0] for a in ModulePermission.ACCESS_CHOICES}
        raw_perms = request.data.get("module_permissions") or {}
        if not isinstance(raw_perms, dict):
            raw_perms = {}
        module_permissions = {
            k: v for k, v in raw_perms.items()
            if k in _valid_modules and v in _valid_levels
        }

        invitation = OrganisationService.invite_member(
            organisation=org,
            email=email,
            role=role,
            invited_by=request.user,
            module_permissions=module_permissions,
        )
        return Response(InvitationSerializer(invitation).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], permission_classes=[IsOwnerOrAdmin], url_path="invitations")
    def list_invitations(self, request, pk=None):
        """GET /organisations/{id}/invitations/ — list all invitations (pending, accepted, rejected)."""
        org = self.get_object()
        invitations = Invitation.objects.filter(organisation=org).select_related(
            "invited_by"
        ).order_by("-created_at")
        return Response(InvitationSerializer(invitations, many=True).data)

    @action(detail=True, methods=["post"], permission_classes=[IsOwnerOrAdmin], url_path="cancel_invitation")
    def cancel_invitation(self, request, pk=None):
        """POST /organisations/{id}/cancel_invitation/ — revoke a pending invitation. Body: { invitation_id }."""
        org = self.get_object()
        invitation_id = request.data.get("invitation_id")
        if not invitation_id:
            return Response({"error": "invitation_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            invitation = Invitation.objects.get(id=invitation_id, organisation=org, is_consumed=False, is_rejected=False)
            invitation.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Invitation.DoesNotExist:
            return Response({"error": "Invitation not found or already consumed."}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=False, methods=["post"], permission_classes=[], throttle_classes=[InvitationRateThrottle])
    def reject_invitation(self, request):
        """POST /organisations/reject_invitation/ — decline an invitation by token. Public — no auth required."""
        token = request.data.get("token")
        if not token:
            return Response({"error": "Token is required."}, status=status.HTTP_400_BAD_REQUEST)
        OrganisationService.reject_invitation(token)
        # Always return 200 regardless of token validity — don't leak whether a token exists
        return Response({"detail": "Invitation declined."})

    @action(detail=False, methods=["get"])
    def my_invitations(self, request):
        """GET /organisations/my_invitations/ — list pending invitations sent to the current user's email."""
        invitations = Invitation.objects.filter(
            email=request.user.email,
            is_consumed=False,
            is_rejected=False,
            expires_at__gte=timezone.now(),
        ).select_related("organisation", "invited_by").order_by("-created_at")
        return Response(InvitationSerializer(invitations, many=True).data)

    @action(detail=True, methods=["post"], permission_classes=[IsOwnerOrAdmin], url_path="remove_logo")
    def remove_logo(self, request, pk=None):
        """POST /organisations/{id}/remove_logo/ — clear the organisation logo."""
        org = self.get_object()
        if org.logo:
            org.logo.delete(save=False)
            org.logo = None
            org.save(update_fields=["logo"])
            try:
                from apps.core.models import AuditLog
                AuditLog.log(action=AuditLog.DELETE, user=request.user, organisation=org,
                             model_name='OrganisationLogo', object_id=str(org.id),
                             object_repr=f'Logo for {org.name}', request=request)
            except Exception:
                pass
        return Response(OrganisationSerializer(org).data)

    @action(detail=True, methods=["post"], permission_classes=[IsOwnerOrAdmin], url_path="remove_stamp")
    def remove_stamp(self, request, pk=None):
        """POST /organisations/{id}/remove_stamp/ — clear the company stamp."""
        org = self.get_object()
        if org.company_stamp:
            org.company_stamp.delete(save=False)
            org.company_stamp = None
            org.save(update_fields=["company_stamp"])
            try:
                from apps.core.models import AuditLog
                AuditLog.log(action=AuditLog.DELETE, user=request.user, organisation=org,
                             model_name='OrganisationStamp', object_id=str(org.id),
                             object_repr=f'Stamp for {org.name}', request=request)
            except Exception:
                pass
        return Response(OrganisationSerializer(org).data)

    @action(detail=True, methods=["post"], permission_classes=[IsOwnerOrAdmin], url_path="upload_logo")
    def upload_logo(self, request, pk=None):
        """
        POST /organisations/{id}/upload_logo/
        Body: raw image binary. Content-Type: image/png | image/jpeg | image/webp

        Accepts raw binary instead of multipart to work around Tauri's IPC layer
        serialising FormData as application/x-www-form-urlencoded.
        """
        from django.core.files.base import ContentFile
        from apps.core.validators import sniff_image_bytes
        _MAX_BYTES = 5 * 1024 * 1024
        org = self.get_object()
        body = request.body
        if not body:
            return Response({"error": {"message": "No file data received."}}, status=status.HTTP_400_BAD_REQUEST)
        if len(body) > _MAX_BYTES:
            return Response({"error": {"message": "File too large. Maximum size is 5 MB."}}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        detected_mime = sniff_image_bytes(body[:261])
        if detected_mime is None:
            return Response({"error": {"message": "File is not a valid image."}}, status=status.HTTP_400_BAD_REQUEST)
        ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}.get(detected_mime, ".jpg")
        if org.logo:
            org.logo.delete(save=False)
        org.logo.save(f"logo_{org.id}{ext}", ContentFile(body), save=True)
        return Response(OrganisationSerializer(org, context={"request": request}).data)

    @action(detail=True, methods=["post"], permission_classes=[IsOwnerOrAdmin], url_path="upload_stamp")
    def upload_stamp(self, request, pk=None):
        """
        POST /organisations/{id}/upload_stamp/
        Body: raw image binary. Content-Type: image/png | image/jpeg | image/webp
        """
        from django.core.files.base import ContentFile
        from apps.core.validators import sniff_image_bytes
        _MAX_BYTES = 5 * 1024 * 1024
        org = self.get_object()
        body = request.body
        if not body:
            return Response({"error": {"message": "No file data received."}}, status=status.HTTP_400_BAD_REQUEST)
        if len(body) > _MAX_BYTES:
            return Response({"error": {"message": "File too large. Maximum size is 5 MB."}}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        detected_mime = sniff_image_bytes(body[:261])
        if detected_mime is None:
            return Response({"error": {"message": "File is not a valid image."}}, status=status.HTTP_400_BAD_REQUEST)
        ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}.get(detected_mime, ".png")
        if org.company_stamp:
            org.company_stamp.delete(save=False)
        org.company_stamp.save(f"stamp_{org.id}{ext}", ContentFile(body), save=True)
        return Response(OrganisationSerializer(org, context={"request": request}).data)

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

    @action(detail=True, methods=["post"], permission_classes=[IsOwnerOrAdmin],
            url_path="create_entity")
    def create_entity(self, request, pk=None):
        """
        POST /tenancy/organisations/{id}/create_entity/
        Creates a child entity under this organisation (Enterprise plan only).
        """
        from apps.subscriptions.models import Subscription
        parent = self.get_object()

        # Check Enterprise plan
        sub = getattr(parent, 'subscription', None)
        plan_slug = sub.plan.slug if sub and sub.plan else ''
        if 'enterprise' not in plan_slug:
            return Response(
                {"error": {"code": "plan_required", "message": "Multi-entity is an Enterprise feature. Upgrade to create child entities."}},
                status=status.HTTP_403_FORBIDDEN,
            )

        name = request.data.get("name", "").strip()
        entity_group_name = request.data.get("entity_group_name", "").strip()
        country = request.data.get("country", parent.country)
        currency = request.data.get("currency", parent.currency)

        if not name:
            return Response(
                {"error": {"code": "validation_error", "message": "Entity name is required."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        child = OrganisationService.create_organisation(
            name=name,
            owner=request.user,
            extra={"country": country, "currency": currency, "account_type": parent.account_type},
        )
        child.parent_org = parent
        child.entity_group_name = entity_group_name or name
        child.save(update_fields=["parent_org", "entity_group_name"])

        return Response(self.get_serializer(child).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], permission_classes=[IsOwnerOrAdmin],
            url_path="entities")
    def entities(self, request, pk=None):
        """
        GET /tenancy/organisations/{id}/entities/
        Lists all child entities of this organisation.
        """
        parent = self.get_object()
        children = parent.child_entities.filter(is_active=True, is_deleted=False)
        return Response(self.get_serializer(children, many=True).data)

    @action(detail=True, methods=["post"], url_path="reseed_coa")
    def reseed_coa(self, request, pk=None):
        """
        POST /tenancy/organisations/{id}/reseed_coa/
        Superuser-only. Re-seeds the chart of accounts for an org that is missing it.
        Safe to call multiple times (idempotent via get_or_create).
        """
        from apps.core.permissions import IsSuperuser
        if not IsSuperuser().has_permission(request, self):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only superusers can reseed chart of accounts.")
        org = self.get_object()
        from apps.accounting.services import AccountingService
        from apps.accounting.models import Account
        before = Account.objects.filter(organisation=org).count()
        AccountingService.seed_chart_of_accounts(org)
        after = Account.objects.filter(organisation=org).count()
        return Response({
            "detail": f"COA reseeded for '{org.name}'.",
            "accounts_before": before,
            "accounts_after": after,
            "accounts_added": after - before,
        })

    @action(detail=False, methods=["post"], throttle_classes=[InvitationRateThrottle])
    def accept_invitation(self, request):
        """Accept a pending invitation using a token."""
        token = request.data.get("token")
        try:
            invitation = Invitation.objects.get(
                token=token,
                is_consumed=False,
                is_rejected=False,
                expires_at__gte=timezone.now(),
            )
        except Invitation.DoesNotExist:
            return Response(
                {"error": {"code": "invalid_token", "message": "Invitation not found or expired."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        membership = OrganisationService.accept_invitation(invitation, request.user)
        return Response(MembershipSerializer(membership).data)

    @action(detail=False, methods=["get"], permission_classes=[], throttle_classes=[InvitationRateThrottle])
    def preview_invitation(self, request):
        """GET /organisations/preview_invitation/?token=... — public endpoint to fetch invite details from an email link."""
        token = request.query_params.get("token")
        if not token:
            return Response({"error": "Token is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            invitation = Invitation.objects.select_related("organisation", "invited_by").get(
                token=token,
            )
        except (Invitation.DoesNotExist, Exception):
            # Return the same 404 for invalid UUIDs and genuinely missing tokens
            return Response(
                {"error": "Invitation not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        # Return only safe public fields — never expose module_permissions or internal IDs
        return Response({
            "token": str(invitation.token),
            "email": invitation.email,
            "role": invitation.role,
            "org_name": invitation.organisation.name,
            "status": invitation.status,
            "invited_by_name": (
                f"{invitation.invited_by.first_name} {invitation.invited_by.last_name}".strip()
                or invitation.invited_by.email
            ),
            "expires_at": invitation.expires_at,
            "created_at": invitation.created_at,
        })

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

        # Enforce member limit (superusers bypass)
        if not request.user.is_superuser:
            max_members = _get_max_team_members(org)
            active_non_owner = Membership.objects.filter(
                organisation=org, is_active=True
            ).exclude(role=Membership.Role.OWNER).count()
            if active_non_owner >= max_members:
                return Response(
                    {"error": {"message": f"Maximum {max_members} team members allowed on your current plan."}},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        username = (request.data.get("username") or "").strip().lower()
        password = request.data.get("password", "").strip()
        role = request.data.get("role", Membership.Role.STAFF)
        first_name = (request.data.get("first_name") or "").strip() or username.capitalize()
        last_name = (request.data.get("last_name") or "").strip()
        notify_email = (request.data.get("notify_email") or "").strip().lower()

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
            first_name=first_name,
            last_name=last_name,
            is_verified=True,
            is_sub_account=True,
            must_change_password=True,
        )
        membership = Membership.objects.create(
            organisation=org,
            user=user,
            role=role,
            invited_by=request.user,
            is_active=True,
        )

        # Send credentials email to the member's personal email if provided
        if notify_email:
            try:
                from django.core.mail import send_mail
                from django.conf import settings as django_settings
                frontend_url = getattr(django_settings, "FRONTEND_URL", "http://localhost:3000")
                from_email = getattr(django_settings, "DEFAULT_FROM_EMAIL", "noreply@auditytechnologies.com")
                display_name = f"{first_name} {last_name}".strip()
                send_mail(
                    subject=f"You've been added to {org.name} on Audity",
                    message=(
                        f"Hi {display_name},\n\n"
                        f"{request.user.get_full_name() or request.user.email} has created an Audity account for you "
                        f"on the {org.name} workspace.\n\n"
                        f"Your login credentials:\n"
                        f"  Email:    {email}\n"
                        f"  Password: {password}\n"
                        f"  Role:     {role.capitalize()}\n\n"
                        f"Sign in at: {frontend_url}/login\n\n"
                        f"For security, please change your password after your first login.\n\n"
                        f"— The Audity Team"
                    ),
                    from_email=from_email,
                    recipient_list=[notify_email],
                    fail_silently=True,
                )
                logger.info("Credentials email sent to %s for sub-account %s", notify_email, email)
            except Exception as exc:
                logger.error("Failed to send credentials email to %s: %s", notify_email, exc)

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
    # IsVerified enforced globally in DRF defaults; explicitly added here because
    # this viewset overrides permission_classes, which would drop the global default.

    def get_permissions(self):
        from apps.core.permissions import IsVerified
        perms = super().get_permissions()
        # Inject IsVerified so unverified users cannot manage team members
        if not any(isinstance(p, IsVerified) for p in perms):
            perms.insert(0, IsVerified())
        return perms

    def get_queryset(self):
        org = getattr(self.request, "organisation", None)
        if org is None:
            # resolve_organisation handles superusers bypassing the membership check
            from apps.tenancy.middleware import resolve_organisation
            org = resolve_organisation(self.request)
        if not org:
            return Membership.objects.none()
        return Membership.objects.filter(organisation=org).select_related("user").prefetch_related("module_permissions")

    def partial_update(self, request, *args, **kwargs):
        """
        PATCH /tenancy/memberships/{id}/
        Intercepts reactivation (is_active: True → False → True) and enforces
        the plan member limit so deactivated + reactivated members can never
        silently exceed the allowed seat count.
        """
        membership = self.get_object()

        # Role changes are an owner-only privilege — admins cannot escalate
        # their own role or anyone else's.
        if "role" in request.data:
            from apps.core.permissions import has_minimum_role
            if not request.user.is_superuser and not has_minimum_role(request.user, membership.organisation, "owner"):
                return Response(
                    {"error": {"message": "Only the organisation owner can change member roles."}},
                    status=status.HTTP_403_FORBIDDEN,
                )
            # Prevent creating a second owner — each org has exactly one.
            if request.data.get("role") == Membership.Role.OWNER:
                return Response(
                    {"error": {"message": "An organisation can only have one owner. Use the ownership transfer flow instead."}},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Only enforce the limit when reactivating a currently inactive member.
        reactivating = (
            not membership.is_active
            and str(request.data.get("is_active", "")).lower() in ("true", "1")
        )

        if reactivating and not request.user.is_superuser:
            org = membership.organisation
            max_members = _get_max_team_members(org)
            active_non_owner = Membership.objects.filter(
                organisation=org, is_active=True
            ).exclude(role=Membership.Role.OWNER).count()
            if active_non_owner >= max_members:
                return Response(
                    {
                        "error": {
                            "message": (
                                f"You have reached the {max_members}-member limit on your plan. "
                                "Deactivate or permanently remove another member before reactivating this one."
                            )
                        }
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        return super().partial_update(request, *args, **kwargs)

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


class PartnerViewSet(viewsets.ViewSet):
    """
    Partner/Accountant channel endpoints.

    GET  /tenancy/partner/profile/        — get or create own partner profile
    PUT  /tenancy/partner/profile/        — update firm name, tier etc.
    GET  /tenancy/partner/clients/        — list managed client orgs
    POST /tenancy/partner/clients/        — add a client org by invite code / org_id
    DELETE /tenancy/partner/clients/{id}/ — remove a client link
    GET  /tenancy/partner/consolidated/   — aggregated dashboard across all clients
    """

    permission_classes = [IsAuthenticated]

    def _get_profile(self, request):
        from .models import PartnerProfile
        profile, _ = PartnerProfile.objects.get_or_create(
            user=request.user,
            defaults={"tier": "starter", "max_clients": 10},
        )
        return profile

    @action(detail=False, methods=["get", "put"], url_path="profile")
    def profile(self, request):
        from .models import PartnerProfile
        from .serializers import PartnerProfileSerializer
        profile = self._get_profile(request)
        if request.method == "PUT":
            serializer = PartnerProfileSerializer(profile, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)
        return Response(PartnerProfileSerializer(profile).data)

    def _provision_membership(self, partner_user, org):
        """
        Auto-create or reactivate a Membership for the partner in the client org
        with accountant role + appropriate ModulePermissions.

        Access matrix (matches senior accountant recommendation):
          - reports, accounting, tax, budget : edit  (core advisory work)
          - sales, purchases, bills, expenses, customers, suppliers, inventory,
            quotes, recurring, payroll         : view  (read all, write nothing)
          - settings                           : none  (no access to billing/config)
        """
        from django.utils import timezone
        from .models import Membership, ModulePermission

        membership, _ = Membership.objects.get_or_create(
            user=partner_user,
            organisation=org,
            defaults={
                "role": Membership.Role.ACCOUNTANT,
                "is_active": True,
                "joined_at": timezone.now(),
            },
        )
        # Reactivate if previously deactivated
        if not membership.is_active:
            membership.is_active = True
            membership.role = Membership.Role.ACCOUNTANT
            membership.save(update_fields=["is_active", "role"])

        # Build permission map
        EDIT_MODULES = {"reports", "accounting", "tax", "budget"}
        VIEW_MODULES = {
            "sales", "purchases", "bills", "expenses", "customers",
            "suppliers", "inventory", "quotes", "recurring", "payroll",
        }
        NO_ACCESS_MODULES = {"settings"}

        module_map = (
            [(m, "edit") for m in EDIT_MODULES]
            + [(m, "view") for m in VIEW_MODULES]
            + [(m, "none") for m in NO_ACCESS_MODULES]
        )
        for module, level in module_map:
            ModulePermission.objects.update_or_create(
                membership=membership,
                module=module,
                defaults={"access_level": level},
            )
        return membership

    def _revoke_membership(self, partner_user, org):
        """Deactivate the partner's membership in the client org."""
        from .models import Membership
        Membership.objects.filter(
            user=partner_user, organisation=org
        ).update(is_active=False)

    @action(detail=False, methods=["get", "post"], url_path="clients")
    def clients(self, request):
        from .models import PartnerClientLink, Organisation
        from .serializers import PartnerClientLinkSerializer
        profile = self._get_profile(request)

        if request.method == "POST":
            org_id = request.data.get("organisation_id")
            notes = request.data.get("notes", "")
            if not org_id:
                return Response({"error": "organisation_id is required"}, status=400)
            try:
                org = Organisation.objects.get(id=org_id)
            except Organisation.DoesNotExist:
                return Response({"error": "Organisation not found"}, status=404)
            # Prevent self-linking (accountant adding their own org as a client)
            if org.owner_id == request.user.id:
                return Response(
                    {"error": "You cannot add your own organisation as a client."},
                    status=400,
                )
            # Security: require an active membership in the target org.
            # The org owner must first invite the partner before they can link it.
            if not Membership.objects.filter(
                user=request.user, organisation=org, is_active=True
            ).exists():
                return Response(
                    {"error": "You must be an invited active member of this organisation to add it as a client. Ask the organisation owner to invite you first."},
                    status=403,
                )
            if not profile.can_add_client:
                return Response(
                    {"error": f"Client limit reached ({profile.max_clients}). Upgrade to Partner Pro or Agency."},
                    status=403,
                )
            # Reject if this org is already an active client of this partner
            existing = PartnerClientLink.objects.filter(
                partner=profile, organisation=org
            ).first()
            if existing:
                if existing.is_active:
                    return Response(
                        {"error": f"{org.name} is already in your client portfolio."},
                        status=400,
                    )
                # Previously removed — reactivate
                existing.is_active = True
                existing.notes = notes or existing.notes
                existing.save()
                self._provision_membership(request.user, org)
                return Response(PartnerClientLinkSerializer(existing).data, status=201)

            link = PartnerClientLink.objects.create(
                partner=profile,
                organisation=org,
                notes=notes,
                is_active=True,
                is_referred=request.data.get("is_referred", True),
            )

            # Provision accountant-role membership in client org
            self._provision_membership(request.user, org)

            return Response(PartnerClientLinkSerializer(link).data, status=201)

        links = profile.clients.filter(is_active=True).select_related("organisation")
        return Response(PartnerClientLinkSerializer(links, many=True).data)

    @action(detail=True, methods=["delete"], url_path="clients")
    def remove_client(self, request, pk=None):
        from .models import PartnerClientLink
        profile = self._get_profile(request)
        try:
            link = PartnerClientLink.objects.get(id=pk, partner=profile)
        except PartnerClientLink.DoesNotExist:
            return Response({"error": "Not found"}, status=404)
        link.is_active = False
        link.save()
        # Revoke accountant membership in client org
        self._revoke_membership(request.user, link.organisation)
        return Response(status=204)

    @action(detail=False, methods=["get"], url_path="consolidated")
    def consolidated(self, request):
        """
        Aggregated metrics across all managed client organisations.
        Returns a summary per client + totals.
        """
        from django.db.models import Sum, Count, Q
        from apps.sales.models import Invoice
        from apps.inventory.models import Product, StockItem
        from apps.customers.models import Customer
        import datetime

        profile = self._get_profile(request)

        # Only include orgs where the partner's Membership is still active.
        # PartnerClientLink.is_active controls the portfolio link but doesn't
        # automatically revoke the Membership row — we re-check both here so
        # a manually deactivated membership doesn't grant continued data access.
        active_member_org_ids = set(
            Membership.objects.filter(
                user=request.user, is_active=True
            ).values_list("organisation_id", flat=True)
        )
        org_ids = [
            oid for oid in
            profile.clients.filter(is_active=True).values_list("organisation_id", flat=True)
            if oid in active_member_org_ids
        ]

        if not org_ids:
            return Response({"clients": [], "totals": {}})

        today = datetime.date.today()
        month_start = today.replace(day=1)

        clients_data = []
        totals = {"total_revenue": 0, "total_outstanding": 0, "total_customers": 0, "total_products": 0}

        for link in profile.clients.filter(is_active=True, organisation_id__in=org_ids).select_related("organisation"):
            org = link.organisation
            oid = org.id

            # Revenue this month
            revenue = Invoice.objects.filter(
                organisation=oid,
                status__in=["paid", "partially_paid", "credit"],
                issue_date__gte=month_start,
            ).aggregate(total=Sum("total_amount"))["total"] or 0

            # Outstanding (overdue + credit)
            outstanding = Invoice.objects.filter(
                organisation=oid,
                status__in=["overdue", "credit", "partially_paid"],
            ).aggregate(total=Sum("amount_due"))["total"] or 0

            # Counts
            customers = Customer.objects.filter(organisation=oid, is_active=True).count()
            products = Product.objects.filter(organisation=oid, is_active=True).count()
            overdue_count = Invoice.objects.filter(organisation=oid, status="overdue").count()

            clients_data.append({
                "link_id": str(link.id),
                "org_id": str(oid),
                "org_name": org.name,
                "org_currency": org.currency,
                "plan": org.subscription.plan.name if hasattr(org, "subscription") else "Unknown",
                "revenue_this_month": float(revenue),
                "outstanding_balance": float(outstanding),
                "overdue_count": overdue_count,
                "total_customers": customers,
                "total_products": products,
                "linked_at": link.linked_at.strftime("%Y-%m-%d"),
            })
            totals["total_revenue"] += float(revenue)
            totals["total_outstanding"] += float(outstanding)
            totals["total_customers"] += customers
            totals["total_products"] += products

        totals["client_count"] = len(clients_data)
        return Response({"clients": clients_data, "totals": totals})
