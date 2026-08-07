"""
Messaging API views.

No WebSockets / Django Channels anywhere in this codebase (confirmed: no
`channels`/`daphne` in requirements, config/asgi.py is unused boilerplate).
Frontend polls: every 5-8s while a thread is open, every 20-30s for the
global unread badge — mirroring apps.payroll's pending_approvals/pending_count
badge-polling convention.

Tenant isolation: Conversation/Message/MessageAttachment are ordinary
TenantAwareModels. Every queryset here is explicitly scoped to
request.organisation on top of participant-level checks — never trust a
single layer.
"""

import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import _get_or_resolve_org

from . import services
from .models import Conversation, ConversationParticipant, Message, MessageAttachment
from .permissions import IsConversationParticipant
from .serializers import (
    ConversationSerializer,
    MessageAttachmentSerializer,
    MessageSerializer,
)

logger = logging.getLogger(__name__)


class ConversationViewSet(viewsets.ModelViewSet):
    """
    /api/v1/messaging/conversations/

    list    — conversations the caller participates in, ordered -last_message_at
              (nulls last).
    create  — direct create() is not the primary entry point; use
              get_or_create_direct/ instead. Left enabled for admin/testing
              convenience but requires kind='direct' and validates participants.
    """

    serializer_class = ConversationSerializer
    permission_classes = [IsAuthenticated, IsConversationParticipant]
    http_method_names = ["get", "post", "head", "options"]

    def _org(self):
        return _get_or_resolve_org(self.request)

    def get_queryset(self):
        org = self._org()
        if org is None:
            return Conversation.objects.none()
        user = self.request.user
        participant_conv_ids = ConversationParticipant.objects.filter(
            organisation=org, user=user, left_at__isnull=True
        ).values_list("conversation_id", flat=True)
        qs = Conversation.objects.filter(
            organisation=org, id__in=participant_conv_ids
        ).prefetch_related("participants")
        # -last_message_at with NULLs last (new/empty conversations sink to
        # the bottom rather than jumping to the top).
        from django.db.models import F

        return qs.order_by(F("last_message_at").desc(nulls_last=True), "-created_at")

    def get_object(self):
        """
        Standard get_queryset() -> get_object_or_404 -> check_object_permissions
        flow, but IsConversationParticipant.has_object_permission raises
        Http404 directly (not PermissionDenied) for non-participants, so a
        probe against a real-but-foreign conversation ID 404s, never 403s.
        """
        org = self._org()
        if org is None:
            raise Http404()
        # Look up by PK across the whole org (not just the caller's participant
        # set) so has_object_permission is the single source of truth for the
        # 404-vs-403 behaviour — filtering it out of the queryset here would
        # also produce 404, but object_permission re-check stays authoritative
        # per the spec ("never trust an upstream queryset filter").
        obj = get_object_or_404(Conversation, pk=self.kwargs["pk"], organisation=org)
        self.check_object_permissions(self.request, obj)
        return obj

    def perform_create(self, serializer):
        org = self._org()
        serializer.save(organisation=org, created_by=self.request.user)

    @action(detail=False, methods=["post"], url_path="get_or_create_direct")
    def get_or_create_direct(self, request):
        """
        POST /conversations/get_or_create_direct/  body: {"other_user_id": "<uuid>"}

        Finds-or-creates a 1:1 thread by pair_key. other_user_id MUST be an
        active member of the SAME resolved org — this is a tenant-isolation
        checkpoint, never allow creating a direct conversation with someone
        outside the caller's org.
        """
        org = self._org()
        if org is None:
            return Response({"error": "Organisation context is missing."}, status=400)

        other_user_id = request.data.get("other_user_id")
        if not other_user_id:
            return Response({"error": "other_user_id is required."}, status=400)

        if str(other_user_id) == str(request.user.id):
            return Response({"error": "Cannot start a conversation with yourself."}, status=400)

        from apps.tenancy.models import Membership

        caller_membership = Membership.objects.filter(
            organisation=org, user=request.user, is_active=True
        ).first()
        if caller_membership is None or caller_membership.role == "employee":
            return Response({"error": "Not permitted."}, status=403)

        other_membership = Membership.objects.filter(
            organisation=org, user_id=other_user_id, is_active=True
        ).select_related("user").first()
        if other_membership is None:
            # Deliberately vague — do not reveal whether the user ID exists
            # anywhere else in the system, only that they're not reachable
            # here.
            return Response(
                {"error": "That user is not a member of this organisation."}, status=404
            )

        conversation, created = services.get_or_create_direct_conversation(
            organisation=org, user=request.user, other_user=other_membership.user
        )
        serializer = self.get_serializer(conversation, context={"request": request})
        return Response(serializer.data, status=201 if created else 200)

    @action(detail=True, methods=["get"], url_path="messages")
    def messages(self, request, pk=None):
        """
        GET /conversations/{id}/messages/?before=<seq>&limit=50

        Cursor pagination strictly on seq. Returns the page ordered oldest
        to newest within the page (most-recent-first page selection, then
        reversed for chat-UI append order).
        """
        conversation = self.get_object()  # 404s for non-participants

        try:
            limit = min(max(int(request.query_params.get("limit", 50)), 1), 200)
        except (TypeError, ValueError):
            limit = 50

        qs = Message.objects.filter(conversation=conversation).order_by("-seq")

        before = request.query_params.get("before")
        if before is not None:
            try:
                before_seq = int(before)
                qs = qs.filter(seq__lt=before_seq)
            except (TypeError, ValueError):
                return Response({"error": "before must be an integer seq value."}, status=400)

        page = list(qs[:limit])
        page.reverse()  # oldest -> newest for the client to render/prepend

        serializer = MessageSerializer(page, many=True, context={"request": request})
        next_before = page[0].seq if page else None
        return Response({
            "results": serializer.data,
            "next_before": next_before,
            "has_more": len(page) == limit,
        })

    @messages.mapping.post
    def send_message(self, request, pk=None):
        """
        POST /conversations/{id}/messages/
        body: {body, client_nonce, attachment_ids?}

        Idempotent on client_nonce: a duplicate (conversation, client_nonce)
        returns the EXISTING message rather than erroring or duplicating.
        """
        conversation = self.get_object()  # 404s for non-participants

        body = (request.data.get("body") or "").strip()
        client_nonce = request.data.get("client_nonce") or None
        attachment_ids = request.data.get("attachment_ids") or []

        if not body and not attachment_ids:
            return Response({"error": "Message body or an attachment is required."}, status=400)

        message, created = services.create_message(
            conversation=conversation,
            sender=request.user,
            body=body,
            client_nonce=client_nonce,
        )

        if created and attachment_ids:
            attachments = MessageAttachment.objects.filter(
                id__in=attachment_ids,
                organisation=conversation.organisation,
                conversation=conversation,
                message__isnull=True,
            )
            attachments.update(message=message)

        serializer = MessageSerializer(message, context={"request": request})
        return Response(serializer.data, status=201 if created else 200)

    @action(detail=True, methods=["post"], url_path="read")
    def read(self, request, pk=None):
        """POST /conversations/{id}/read/ — bump caller's last_read_seq."""
        conversation = self.get_object()
        participant = services.mark_read(conversation=conversation, user=request.user)
        return Response({
            "conversation_id": str(conversation.id),
            "last_read_seq": participant.last_read_seq,
            "last_seq": conversation.last_seq,
        })

    @action(detail=True, methods=["post"], url_path="attachments")
    def attachments(self, request, pk=None):
        """
        POST /conversations/{id}/attachments/
        Two-step upload: create a standalone MessageAttachment (message=None),
        return its id for use in a subsequent messages/ POST's attachment_ids.
        """
        conversation = self.get_object()
        file_obj = request.FILES.get("file")
        if file_obj is None:
            return Response({"error": "file is required."}, status=400)

        attachment = MessageAttachment.objects.create(
            organisation=conversation.organisation,
            conversation=conversation,
            message=None,
            file=file_obj,
            file_name=getattr(file_obj, "name", "") or "",
            file_size=getattr(file_obj, "size", 0) or 0,
            content_type=getattr(file_obj, "content_type", "") or "",
        )
        serializer = MessageAttachmentSerializer(attachment, context={"request": request})
        return Response(serializer.data, status=201)


class MessageAttachmentDownloadView(APIView):
    """
    GET /api/v1/messaging/attachments/{id}/download/

    Authenticated, participant-gated attachment retrieval. MessageAttachment.file
    must NEVER be exposed as a directly browsable storage URL (raw MEDIA_URL /
    S3 URL) — see MessageAttachmentSerializer, which deliberately does not
    serialize the raw `file` field. This view is the only sanctioned path to
    the bytes.

    Access control: IsConversationParticipant.has_object_permission against
    the attachment's parent conversation — same 404-not-403 behaviour as
    every other messaging endpoint (a non-participant, including someone in
    a completely unrelated org, gets a 404, never a redirect or a stream).

    Storage backends:
      - Local/dev (FileSystemStorage): stream the file directly via
        FileResponse once permission passes. No X-Sendfile/X-Accel-Redirect
        (no nginx config confirmed in this repo).
      - S3/R2 (USE_S3=True): redirect (302) to a short-TTL pre-signed URL
        rather than proxying the bytes through Django. AWS_QUERYSTRING_AUTH
        is True in production settings, so storage.url() already returns a
        signed URL — we just clamp its expiry to a short-lived window for
        this specific redirect rather than trusting the (longer) default
        AWS_QUERYSTRING_EXPIRE.
    """

    permission_classes = [IsAuthenticated]

    # Short-lived signed-URL TTL for the S3 redirect path — deliberately
    # much shorter than the default AWS_QUERYSTRING_EXPIRE (1 hour) since
    # this URL is handed straight to the browser for immediate use.
    PRESIGNED_URL_TTL_SECONDS = 120

    def get(self, request, pk=None):
        attachment = get_object_or_404(MessageAttachment, pk=pk)

        permission = IsConversationParticipant()
        if not permission.has_permission(request, self):
            raise Http404()
        permission.has_object_permission(request, self, attachment)

        if not attachment.file:
            raise Http404()

        # There is no USE_S3 flag exposed on `settings` (production.py only
        # keeps it as a local `_use_s3` at settings-load time) — detect the
        # active storage backend directly instead of requiring one.
        use_s3 = type(attachment.file.storage).__name__ == "S3Boto3Storage"

        if use_s3:
            try:
                signed_url = attachment.file.storage.url(
                    attachment.file.name, expire=self.PRESIGNED_URL_TTL_SECONDS
                )
            except TypeError:
                # Older django-storages signature without `expire` kwarg —
                # fall back to the storage's configured default expiry.
                signed_url = attachment.file.url
            from django.shortcuts import redirect

            return redirect(signed_url)

        try:
            file_handle = attachment.file.open("rb")
        except FileNotFoundError:
            raise Http404()

        response = FileResponse(
            file_handle,
            content_type=attachment.content_type or "application/octet-stream",
        )
        download_name = attachment.file_name or attachment.file.name.rsplit("/", 1)[-1]
        response["Content-Disposition"] = f'attachment; filename="{download_name}"'
        return response


class UnreadCountView(APIView):
    """
    GET /api/v1/messaging/unread_count/

    Org-scoped total unread for the current user:
        sum(conversation.last_seq - participant.last_read_seq)
    computed via aggregation over ConversationParticipant, never a
    per-message table scan.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = _get_or_resolve_org(request)
        if org is None:
            return Response({"unread_count": 0})

        from apps.tenancy.models import Membership

        membership = Membership.objects.filter(
            organisation=org, user=request.user, is_active=True
        ).first()
        if membership is None or membership.role == "employee":
            return Response({"unread_count": 0})

        from django.db.models import F, Sum
        from django.db.models.functions import Greatest
        from django.db.models import Value, IntegerField

        total = (
            ConversationParticipant.objects.filter(
                organisation=org, user=request.user, left_at__isnull=True
            )
            .annotate(
                unread=Greatest(
                    F("conversation__last_seq") - F("last_read_seq"),
                    Value(0, output_field=IntegerField()),
                )
            )
            .aggregate(total=Sum("unread"))["total"]
            or 0
        )
        return Response({"unread_count": total})


class PartnerInboxView(APIView):
    """
    GET /api/v1/messaging/partner_inbox/

    Partner-only: requires the caller has an active PartnerProfile. Fans out
    over the partner's OWN PartnerClientLink rows (bounded to that partner's
    linked client orgs — never iterated over every org in the system) and
    returns per-client-org unread count + last message preview.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = getattr(request.user, "partner_profile", None)
        if profile is None or not profile.is_active:
            return Response(
                {"error": "This endpoint is only available to active partner accounts."},
                status=403,
            )

        from apps.tenancy.models import PartnerClientLink

        links = PartnerClientLink.objects.filter(
            partner=profile, is_active=True
        ).select_related("organisation")

        from django.db.models import F, Sum, Value, IntegerField
        from django.db.models.functions import Greatest

        results = []
        for link in links:
            org = link.organisation
            participants = ConversationParticipant.objects.filter(
                organisation=org, user=request.user, left_at__isnull=True
            ).annotate(
                unread=Greatest(
                    F("conversation__last_seq") - F("last_read_seq"),
                    Value(0, output_field=IntegerField()),
                )
            )
            unread_total = participants.aggregate(total=Sum("unread"))["total"] or 0

            latest_conv = (
                Conversation.objects.filter(
                    organisation=org,
                    id__in=participants.values_list("conversation_id", flat=True),
                )
                .order_by("-last_message_at")
                .first()
            )
            results.append({
                "organisation_id": str(org.id),
                "organisation_name": org.name,
                "unread_count": unread_total,
                "last_message_preview": latest_conv.last_message_preview if latest_conv else "",
                "last_message_at": latest_conv.last_message_at if latest_conv else None,
                "conversation_id": str(latest_conv.id) if latest_conv else None,
            })

        results.sort(key=lambda r: r["unread_count"], reverse=True)
        return Response({"results": results})


class MessageSearchView(APIView):
    """
    GET /api/v1/messaging/search/?q=

    body__icontains, scoped strictly to the caller's own conversations
    (via active ConversationParticipant rows) in the resolved org.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = _get_or_resolve_org(request)
        query = (request.query_params.get("q") or "").strip()
        if org is None or not query:
            return Response({"results": []})

        from apps.tenancy.models import Membership

        membership = Membership.objects.filter(
            organisation=org, user=request.user, is_active=True
        ).first()
        if membership is None or membership.role == "employee":
            return Response({"results": []})

        conv_ids = ConversationParticipant.objects.filter(
            organisation=org, user=request.user, left_at__isnull=True
        ).values_list("conversation_id", flat=True)

        messages = (
            Message.objects.filter(
                organisation=org, conversation_id__in=conv_ids, body__icontains=query
            )
            .select_related("conversation", "sender")
            .order_by("-seq")[:100]
        )
        serializer = MessageSerializer(messages, many=True, context={"request": request})
        return Response({"results": serializer.data})
