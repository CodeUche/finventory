"""
Platform admin API — superusers only.
Provides cross-tenant aggregate statistics.
"""
from django.db.models import Count, Q, Sum
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsSuperuser, IsOwnerOrAdmin, IsVerified, _get_or_resolve_org


class AuditLogView(APIView):
    """
    GET /api/v1/audit-log/

    Returns audit log entries scoped to the current organisation.
    Accessible to org owners/admins and superusers.
    Supports filters: model, action, date_from, date_to.
    """
    permission_classes = [IsAuthenticated, IsVerified]

    def get(self, request):
        from apps.core.models import AuditLog

        is_superuser = request.user.is_superuser
        org = _get_or_resolve_org(request)

        # Permission check: must be superuser OR org owner/admin
        if not is_superuser:
            if not org:
                return Response(
                    {'error': 'Organisation context required.'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            from apps.core.permissions import has_minimum_role
            if not has_minimum_role(request.user, org, 'admin'):
                return Response(
                    {'error': 'Owner or Admin role required.'},
                    status=status.HTTP_403_FORBIDDEN,
                )

        qs = AuditLog.objects.all()

        # Scope to org (always for non-superusers; by context for superusers)
        if org:
            qs = qs.filter(organisation_id=org.id)

        # Filters
        model = request.query_params.get('model')
        action = request.query_params.get('action')
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')

        if model:
            qs = qs.filter(model_name__iexact=model)
        if action:
            qs = qs.filter(action=action)
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        # Add user search filter (require 2+ chars to avoid full-table wildcard scans)
        user_search = request.query_params.get('user')
        if user_search and len(user_search.strip()) >= 2:
            qs = qs.filter(user_email__icontains=user_search.strip())

        # IP filter
        ip_search = request.query_params.get('ip')
        if ip_search and len(ip_search.strip()) >= 2:
            qs = qs.filter(ip_address__icontains=ip_search.strip())

        # ── CSV export (?export=csv) — streams the filtered set (capped) ──────
        if request.query_params.get('export') == 'csv':
            import csv
            from django.http import StreamingHttpResponse

            # Auditing the audit: record who exported the trail.
            AuditLog.log(action=AuditLog.EXPORT, user=request.user, organisation=org,
                         model_name='audit-log', object_repr='Audit log CSV export',
                         request=request,
                         is_owner_action=bool(org and org.owner_id == request.user.id))

            def rows():
                header = ['timestamp', 'user', 'action', 'model', 'object_id',
                          'object', 'ip_address', 'owner_action']
                buf = __import__('io').StringIO()
                w = csv.writer(buf)
                w.writerow(header)
                yield buf.getvalue()
                for e in qs.iterator(chunk_size=500):
                    buf.seek(0); buf.truncate(0)
                    w.writerow([
                        e.created_at.isoformat(), e.user_email, e.action,
                        e.model_name, e.object_id, e.object_repr,
                        e.ip_address or '', 'yes' if e.is_owner_action else 'no',
                    ])
                    yield buf.getvalue()

            from django.utils import timezone as _tz
            resp = StreamingHttpResponse(rows(), content_type='text/csv')
            resp['Content-Disposition'] = (
                f'attachment; filename="audit-log-{_tz.now().date().isoformat()}.csv"'
            )
            return resp

        # ── Pagination (?page=N&page_size=M). Legacy clients that send only
        #    `limit` keep the old flat-list response shape. ────────────────────
        paginated = 'page' in request.query_params
        if paginated:
            try:
                page_size = min(max(int(request.query_params.get('page_size', 50)), 1), 200)
            except (TypeError, ValueError):
                page_size = 50
            try:
                page = max(int(request.query_params.get('page', 1)), 1)
            except (TypeError, ValueError):
                page = 1
            total = qs.count()
            start = (page - 1) * page_size
            entries = qs[start:start + page_size]
        else:
            try:
                limit = min(int(request.query_params.get('limit', 500)), 500)
            except (TypeError, ValueError):
                limit = 500
            entries = qs[:max(limit, 1)]

        data = []
        for entry in entries:
            changes = entry.changes or {}
            # Build a clean field-level diff list
            change_list = []
            if isinstance(changes, dict):
                for field, val in changes.items():
                    if isinstance(val, dict) and 'old' in val and 'new' in val:
                        change_list.append({'field': field, 'old': val['old'], 'new': val['new']})
                    else:
                        change_list.append({'field': field, 'old': None, 'new': val})

            data.append({
                'id': str(entry.id),
                'timestamp': entry.created_at.isoformat(),
                'user_email': entry.user_email,
                'action': entry.action,
                'model': entry.model_name,
                'object_id': entry.object_id,
                'object_repr': entry.object_repr,
                'changes': change_list,
                'ip_address': entry.ip_address,
                'user_agent': entry.user_agent,
                'actor_label': entry.actor_label,
                'is_owner_action': entry.is_owner_action,
            })

        if paginated:
            import math
            return Response({
                'results': data,
                'count': total,
                'page': page,
                'page_size': page_size,
                'pages': max(math.ceil(total / page_size), 1),
            })
        return Response(data)


class PlatformStatsView(APIView):
    permission_classes = [IsAuthenticated, IsSuperuser]

    def get(self, request):
        from apps.tenancy.models import Organisation, Membership
        from apps.authentication.models import User
        from apps.subscriptions.models import Plan
        from apps.sales.models import Invoice
        from django.db import connection as _conn

        # Bypass RLS for this superuser-only, cross-tenant stats endpoint.
        # Without this, Invoice queries run as `audity_app` with the SENTINEL
        # GUC (no X-Organisation-ID on the request), so RLS on sales_invoice
        # silently returns 0 rows, making invoice counts and revenue wrong.
        # SET LOCAL scopes the bypass to the current transaction only.
        try:
            with _conn.cursor() as cur:
                cur.execute("SET LOCAL row_security = OFF")
        except Exception:
            pass  # Non-superuser DB role — fall through, queries return what RLS allows

        orgs = Organisation.objects.filter(is_deleted=False)
        users = User.objects.filter(is_active=True)
        invoices = Invoice.objects.all()

        # Single annotated query — no per-org N+1.
        # Membership.organisation FK has related_name="memberships" (defined
        # directly on the model, not via TenantAwareModel's pattern).
        # Invoice.organisation FK uses TenantAwareModel's pattern → "sales_invoice_set".
        org_qs = (
            orgs
            .select_related('owner', 'subscription__plan')
            .annotate(
                member_count=Count('memberships', filter=Q(memberships__is_active=True), distinct=True),
                invoice_count=Count('sales_invoice_set', distinct=True),
                total_revenue=Sum(
                    'sales_invoice_set__total_amount',
                    filter=Q(sales_invoice_set__status__in=['paid', 'partially_paid', 'confirmed']),
                ),
            )
        )

        org_data = []
        for org in org_qs:
            org_data.append({
                'id': str(org.id),
                'name': org.name,
                'owner_email': org.owner.email if org.owner else None,
                'currency': org.currency,
                'country': org.country,
                'plan': (org.subscription.plan.name if org.subscription and org.subscription.plan else 'None'),
                'sub_status': org.subscription.status if org.subscription else 'none',
                'member_count': org.member_count or 0,
                'invoice_count': org.invoice_count or 0,
                'total_revenue': str(org.total_revenue or 0),
                'is_active': org.is_active,
                'created_at': org.created_at.isoformat(),
            })

        return Response({
            'summary': {
                'total_orgs': orgs.count(),
                'active_orgs': orgs.filter(is_active=True).count(),
                'total_users': users.count(),
                'superusers': users.filter(is_superuser=True).count(),
                'total_invoices': invoices.count(),
                'total_revenue': str(
                    invoices.filter(status__in=['paid', 'partially_paid', 'confirmed'])
                    .aggregate(s=Sum('total_amount'))['s'] or 0
                ),
                'plans': list(Plan.objects.values('name', 'price', 'is_active').order_by('price')),
            },
            'organisations': org_data,
        })


class _AdminUserPagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 500


class PlatformUsersView(APIView):
    permission_classes = [IsAuthenticated, IsSuperuser]

    def get(self, request):
        from apps.authentication.models import User

        qs = (
            User.objects
            .prefetch_related('memberships__organisation__owner')
            .order_by('-created_at')
        )

        paginator = _AdminUserPagination()
        page = paginator.paginate_queryset(qs, request)

        data = []
        for u in (page if page is not None else qs):
            memberships = [m for m in u.memberships.all() if m.is_active]
            data.append({
                'id': str(u.id),
                'email': u.email,
                'first_name': u.first_name,
                'last_name': u.last_name,
                'is_superuser': u.is_superuser,
                'is_active': u.is_active,
                'is_verified': u.is_verified,
                'created_at': u.created_at.isoformat(),
                'orgs': [
                    {
                        'name': m.organisation.name,
                        'role': m.role,
                        'owner_email': m.organisation.owner.email if m.organisation.owner else None,
                    }
                    for m in memberships
                ],
            })

        if page is not None:
            return paginator.get_paginated_response(data)
        return Response(data)


class PlatformUserDetailView(APIView):
    """
    PATCH /api/v1/platform-admin/users/{id}/  — deactivate / reactivate a user (superuser only)
    DELETE /api/v1/platform-admin/users/{id}/ — permanently delete a user (superuser only)

    Deactivating an owner automatically cascades to all sub-accounts in their orgs
    via the pre_save signal in apps.tenancy.signals.
    """
    permission_classes = [IsAuthenticated, IsSuperuser]

    def _get_user(self, pk):
        from apps.authentication.models import User
        try:
            return User.objects.get(pk=pk)
        except User.DoesNotExist:
            return None

    def patch(self, request, pk):
        user = self._get_user(pk)
        if not user:
            return Response({'error': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)
        if user.is_superuser and not request.user.is_superuser:
            return Response({'error': 'Cannot modify a superuser.'}, status=status.HTTP_403_FORBIDDEN)

        is_active = request.data.get('is_active')
        if is_active is None:
            return Response({'error': 'is_active field required.'}, status=status.HTTP_400_BAD_REQUEST)

        # Signal fires on save and cascades to sub-accounts if deactivating an owner
        user.is_active = bool(is_active)
        user.save(update_fields=['is_active'])

        action = 'reactivated' if user.is_active else 'deactivated'
        return Response({'detail': f'User {user.email} {action}.', 'is_active': user.is_active})

    def delete(self, request, pk):
        user = self._get_user(pk)
        if not user:
            return Response({'error': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)
        if user.is_superuser:
            return Response(
                {'error': 'Cannot delete a superuser via this endpoint. Use the Django admin.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        email = user.email
        user_id = str(user.pk)
        # Deactivate first so signal cascades to sub-accounts before hard delete
        user.is_active = False
        user.save(update_fields=['is_active'])
        user.delete()
        try:
            from apps.core.models import AuditLog
            AuditLog.log(
                action=AuditLog.DELETE,
                user=request.user,
                model_name='User',
                object_id=user_id,
                object_repr=email,
                request=request,
            )
        except Exception:
            pass
        return Response({'detail': f'User {email} permanently deleted.'}, status=status.HTTP_200_OK)
