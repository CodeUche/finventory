"""
Platform admin API — superusers only.
Provides cross-tenant aggregate statistics.
"""
from django.db.models import Count, Sum
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsSuperuser, IsOwnerOrAdmin, _get_or_resolve_org


class AuditLogView(APIView):
    """
    GET /api/v1/audit-log/

    Returns audit log entries scoped to the current organisation.
    Accessible to org owners/admins and superusers.
    Supports filters: model, action, date_from, date_to.
    """
    permission_classes = [IsAuthenticated]

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

        data = []
        for entry in qs[:500]:
            changes = entry.changes
            if isinstance(changes, dict) and changes:
                summary = ', '.join(f"{k}: {v}" for k, v in list(changes.items())[:3])
            else:
                summary = ''
            data.append({
                'id': str(entry.id),
                'timestamp': entry.created_at.isoformat(),
                'user': str(entry.user_id) if entry.user_id else '',
                'user_email': entry.user_email,
                'action': entry.action,
                'model': entry.model_name,
                'object_repr': entry.object_repr,
                'changes_summary': summary,
            })

        return Response(data)


class PlatformStatsView(APIView):
    permission_classes = [IsAuthenticated, IsSuperuser]

    def get(self, request):
        from apps.tenancy.models import Organisation, Membership
        from apps.authentication.models import User
        from apps.subscriptions.models import Plan, Subscription
        from apps.sales.models import Invoice
        from apps.expenses.models import Expense

        orgs = Organisation.objects.filter(is_deleted=False)
        users = User.objects.filter(is_active=True)
        invoices = Invoice.objects.all()
        subs = Subscription.objects.select_related('plan', 'organisation')

        # Org list with key info
        org_data = []
        for org in orgs.select_related('owner', 'subscription__plan'):
            member_count = Membership.objects.filter(organisation=org, is_active=True).count()
            invoice_count = Invoice.objects.filter(organisation=org).count()
            total_revenue = Invoice.objects.filter(
                organisation=org, status__in=['paid', 'partially_paid', 'confirmed']
            ).aggregate(s=Sum('total_amount'))['s'] or 0
            org_data.append({
                'id': str(org.id),
                'name': org.name,
                'owner_email': org.owner.email if org.owner else None,
                'currency': org.currency,
                'country': org.country,
                'plan': org.subscription.plan.name if org.subscription else 'None',
                'sub_status': org.subscription.status if org.subscription else 'none',
                'member_count': member_count,
                'invoice_count': invoice_count,
                'total_revenue': str(total_revenue),
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


class PlatformUsersView(APIView):
    permission_classes = [IsAuthenticated, IsSuperuser]

    def get(self, request):
        from apps.authentication.models import User
        from apps.tenancy.models import Membership

        users = User.objects.all().order_by('-created_at')
        data = []
        for u in users:
            memberships = Membership.objects.filter(user=u, is_active=True).select_related('organisation')
            data.append({
                'id': str(u.id),
                'email': u.email,
                'first_name': u.first_name,
                'last_name': u.last_name,
                'is_superuser': u.is_superuser,
                'is_active': u.is_active,
                'is_verified': u.is_verified,
                'created_at': u.created_at.isoformat(),
                'orgs': [{'name': m.organisation.name, 'role': m.role} for m in memberships],
            })
        return Response(data)
