"""Tenancy views: Organisations, Memberships, Invitations."""

from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import IsOwnerOrAdmin

from .models import Invitation, Membership, Organisation
from .serializers import InvitationSerializer, MembershipSerializer, OrganisationSerializer
from .services import OrganisationService


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

    @action(detail=True, methods=["post"], permission_classes=[IsOwnerOrAdmin])
    def invite(self, request, pk=None):
        """Send an invitation to join this organisation."""
        org = self.get_object()
        invitation = OrganisationService.invite_member(
            organisation=org,
            email=request.data.get("email"),
            role=request.data.get("role", Membership.Role.STAFF),
            invited_by=request.user,
        )
        return Response(InvitationSerializer(invitation).data, status=status.HTTP_201_CREATED)

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


class MembershipViewSet(viewsets.ModelViewSet):
    """Manage members of the current organisation."""

    serializer_class = MembershipSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

    def get_queryset(self):
        org = getattr(self.request, "organisation", None)
        if not org:
            return Membership.objects.none()
        return Membership.objects.filter(organisation=org).select_related("user")
