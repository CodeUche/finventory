"""
Messaging permissions.

Modeled on apps.payroll.permissions.IsEmployeeSelf. Key property: a
non-participant must get a 404 on object access, never a 403 — so the mere
existence of a conversation/message is not leaked to someone outside it.

Scope awareness: a partner-contact's Membership can carry the ACCOUNTANT
role (granted for 'operational' or 'both' scope, per
apps.tenancy.views._provision_partner_membership) purely for non-messaging
workflows (payroll/salary access etc). role == 'accountant' alone is NOT
sufficient to grant messaging — Membership.granted_scope must also be
'messaging_only' or 'both'. Ordinary (non-partner) memberships have
granted_scope == '' and are unaffected by this check (only ever set by the
partner-provisioning flow).
"""

from django.http import Http404
from rest_framework.permissions import BasePermission

from apps.core.permissions import _get_or_resolve_org


def _get_membership(request):
    """Return the caller's active Membership in the resolved org, or None."""
    org = _get_or_resolve_org(request)
    if org is None:
        return None
    from apps.tenancy.models import Membership

    return (
        Membership.objects.filter(organisation=org, user=request.user, is_active=True)
        .select_related("organisation")
        .first()
    )


class IsConversationParticipant(BasePermission):
    """
    Access control for messaging endpoints.

    has_permission (list/create-level):
        - Must be authenticated.
        - Blanket denial if the caller's Membership.role in the resolved org
          IS 'employee' — belt-and-suspenders on top of ROLE_HIERARCHY.
        - For list/create: caller must have an active Membership in this org
          (any non-employee role can create a new conversation with another
          active member; participation in specific conversations is
          re-checked per-object below).

    has_object_permission:
        - RE-CHECKS the specific conversation's participant row for the
          requesting user on every access — never trusts an upstream
          queryset filter. If the caller is not an active participant, this
          raises Http404 directly (not PermissionDenied) so a non-participant
          gets a true 404, not a 403 that would leak the object's existence.
    """

    message = "You do not have access to this conversation."

    # Grants under this scope (payroll/salary etc — see
    # apps.tenancy.views._provision_partner_membership) never get messaging,
    # regardless of the role they carry.
    _MESSAGING_DENIED_SCOPES = {"operational"}

    @staticmethod
    def _scope_denies_messaging(membership) -> bool:
        granted_scope = getattr(membership, "granted_scope", "") or ""
        return granted_scope in IsConversationParticipant._MESSAGING_DENIED_SCOPES

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False

        membership = _get_membership(request)
        if membership is None:
            return False

        # Explicit employee-role blanket denial (belt-and-suspenders on top
        # of ROLE_HIERARCHY placement).
        if membership.role == "employee":
            return False

        # An operational-scope partner grant (role=accountant, granted for
        # payroll/salary access) must not reach messaging even though its
        # role would otherwise pass every other check here.
        if self._scope_denies_messaging(membership):
            return False

        request.messaging_membership = membership
        return True

    def has_object_permission(self, request, view, obj):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            raise Http404()

        membership = getattr(request, "messaging_membership", None) or _get_membership(request)
        if membership is None or membership.role == "employee":
            raise Http404()
        if self._scope_denies_messaging(membership):
            raise Http404()

        conversation = self._resolve_conversation(obj)
        if conversation is None:
            raise Http404()

        from .models import ConversationParticipant

        is_participant = ConversationParticipant.objects.filter(
            conversation=conversation, user=user, left_at__isnull=True
        ).exists()
        if not is_participant:
            raise Http404()
        return True

    @staticmethod
    def _resolve_conversation(obj):
        """obj may be a Conversation, Message, or MessageAttachment."""
        from .models import Conversation

        if isinstance(obj, Conversation):
            return obj
        return getattr(obj, "conversation", None)
