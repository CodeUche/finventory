"""
Core permission classes and RBAC helpers.

Role hierarchy (highest to lowest):
    OWNER → ADMIN → MANAGER → ACCOUNTANT → STAFF → VIEWER

Each role includes all permissions of roles below it.

Design note on DRF + JWT + Middleware order:
    Django middleware runs before DRF authentication. When permission classes
    execute, DRF has already authenticated the user via JWT, but
    request.organisation may still be None (set by TenantMiddleware phase 1).
    All permission helpers call _get_or_resolve_org() which triggers the
    phase-2 tenant resolution if needed.
"""

from rest_framework.permissions import BasePermission

ROLE_HIERARCHY = {
    "owner": 100,
    "admin": 80,
    "manager": 60,
    "accountant": 40,
    "staff": 20,
    "viewer": 10,
    # Employee self-service. Deliberately below viewer so that every existing
    # IsStaff / IsViewer gate refuses it — an employee reaches their own data
    # through IsEmployeeSelf on the /me endpoints and nowhere else.
    "employee": 5,
    # Partner contact (messaging-only). Deliberately below viewer (and even
    # below employee — the exact position relative to employee doesn't matter,
    # only that it stays under viewer=10) so every existing IsStaff / IsViewer /
    # role-gated endpoint refuses it automatically — a partner_contact
    # membership reaches conversations through IsConversationParticipant in
    # apps.messaging and nowhere else.
    "partner_contact": 8,
}


def _get_or_resolve_org(request):
    """
    Return request.organisation, resolving from JWT context if not yet set.

    Permissions run after DRF auth but request.organisation is only
    populated by middleware phase-1 (which captures the org ID).
    Phase-2 validation happens here when needed.
    """
    org = getattr(request, "organisation", None)
    if org is None and request.user and request.user.is_authenticated:
        from apps.tenancy.middleware import resolve_organisation
        org = resolve_organisation(request)
    return org


def has_minimum_role(user, organisation, minimum_role: str) -> bool:
    """Returns True if user holds at least minimum_role in the given org."""
    try:
        membership = user.memberships.select_related("organisation").get(
            organisation=organisation,
            is_active=True,
        )
        user_level = ROLE_HIERARCHY.get(membership.role, 0)
        required_level = ROLE_HIERARCHY.get(minimum_role, 999)
        return user_level >= required_level
    except Exception:
        return False


class IsTenantMember(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        org = _get_or_resolve_org(request)
        if not org:
            return False
        return request.user.memberships.filter(organisation=org, is_active=True).exists()


class IsOwnerOrAdmin(BasePermission):
    def has_permission(self, request, view):
        if request.user and request.user.is_superuser:
            # Still resolve+attach the org so request.organisation is populated
            # for any view/action that reads it directly instead of going
            # through TenantFilterMixin.get_queryset(). Without this, superuser
            # requests pass permission with request.organisation left as None.
            _get_or_resolve_org(request)
            return True
        org = _get_or_resolve_org(request)
        return bool(org and has_minimum_role(request.user, org, "admin"))


class IsManager(BasePermission):
    def has_permission(self, request, view):
        if request.user and request.user.is_superuser:
            _get_or_resolve_org(request)
            return True
        org = _get_or_resolve_org(request)
        return bool(org and has_minimum_role(request.user, org, "manager"))


class IsAccountant(BasePermission):
    def has_permission(self, request, view):
        if request.user and request.user.is_superuser:
            _get_or_resolve_org(request)
            return True
        org = _get_or_resolve_org(request)
        return bool(org and has_minimum_role(request.user, org, "accountant"))


class IsStaff(BasePermission):
    def has_permission(self, request, view):
        if request.user and request.user.is_superuser:
            _get_or_resolve_org(request)
            return True
        org = _get_or_resolve_org(request)
        return bool(org and has_minimum_role(request.user, org, "staff"))


class IsReadOnly(BasePermission):
    def has_permission(self, request, view):
        return request.method in ("GET", "HEAD", "OPTIONS")


class IsOwnerOfObject(BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        created_by = getattr(obj, "created_by", None)
        return created_by is not None and created_by == request.user


class IsSuperuser(BasePermission):
    """Only Django superusers can access this endpoint."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


class IsManagerOrSuperuser(BasePermission):
    """Allows org managers/admins/owners AND platform superusers."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            _get_or_resolve_org(request)
            return True
        org = _get_or_resolve_org(request)
        return bool(org and has_minimum_role(request.user, org, 'manager'))


class IsVerified(BasePermission):
    """
    Blocks unverified users from accessing tenant data.
    Users must click the verification link sent to their email after registration.
    """
    message = "Please verify your email address before accessing this resource."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_verified)


def plan_denial(org, module_key: str):
    """Why the organisation's plan does not allow `module_key`, or None if it does.

    Shared by plan_requires (the viewset gate) and user_can_run_report, so the two
    can never disagree. Rules:
    - no subscription: allowed (prevents lockout during onboarding)
    - inactive/expired subscription: denied
    - plan has no modules list: unrestricted (legacy/development plans)
    - otherwise the module must be in the plan's modules list
    """
    sub = getattr(org, "subscription", None)
    if sub is None:
        return None
    if not sub.is_active:
        return (
            "Your subscription has expired. Renew or switch plans to "
            "regain access to this feature."
        )
    modules = sub.plan.features.get("modules") if sub.plan.features else None
    if not modules:
        return None
    if module_key not in modules:
        return (
            f"Your {sub.plan.name} plan does not include {module_key.replace('_', ' ').title()}. "
            "Upgrade your plan to access this feature."
        )
    return None


def plan_requires(module_key: str):
    """
    Factory that returns a DRF permission class gating access to a specific
    plan module.

    Usage::
        permission_classes = [IsAuthenticated, IsStaff, plan_requires('payroll')]

    Rules (see plan_denial): superusers bypass; no subscription is allowed; an
    inactive subscription or a plan without the module is denied (HTTP 402 via
    the message). Applies to ALL HTTP methods, GET included, matching the
    sidebar gating.
    """
    class _PlanModulePermission(BasePermission):
        message = (
            "Your current plan does not include access to this feature. "
            "Upgrade your plan to continue."
        )

        def has_permission(self, request, view):
            if request.user and request.user.is_superuser:
                _get_or_resolve_org(request)
                return True
            org = _get_or_resolve_org(request)
            if not org:
                return False
            denial = plan_denial(org, module_key)
            if denial:
                self.message = denial
                return False
            return True

    _PlanModulePermission.__name__ = f"PlanRequires_{module_key}"
    _PlanModulePermission.__qualname__ = f"PlanRequires_{module_key}"
    return _PlanModulePermission


class SubscriptionActive(BasePermission):
    """
    Blocks write requests (POST/PUT/PATCH/DELETE) when the organisation's
    subscription is expired, canceled, or unpaid.

    Read requests (GET/HEAD/OPTIONS) always pass — users can still view
    existing data after expiry but cannot create new records.

    Superusers bypass this check.
    """
    message = "Your subscription is inactive. Upgrade your plan to continue using this feature."

    def has_permission(self, request, view):
        # Safe methods always allowed
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        # Superusers bypass
        if request.user and request.user.is_superuser:
            _get_or_resolve_org(request)
            return True
        org = _get_or_resolve_org(request)
        if org is None:
            return False
        sub = getattr(org, "subscription", None)
        if sub is None:
            # No subscription — allow (prevents lockout before plans are seeded)
            return True
        return sub.is_active


class PlanMemberLimitActive(BasePermission):
    """
    Enforces member limits on every request after a plan downgrade.

    When an org's active non-owner member count exceeds the plan's max_users,
    non-owner members are blocked with HTTP 402 until the owner upgrades or
    deactivates excess members. Owners, admins, and superusers are never blocked.
    """
    message = (
        "Your organisation has exceeded the member limit for its current plan. "
        "The account owner must upgrade or deactivate excess members."
    )

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return True  # Let auth classes handle unauthenticated requests
        if request.user.is_superuser:
            _get_or_resolve_org(request)
            return True
        org = _get_or_resolve_org(request)
        if org is None:
            return True  # No org context — let other permissions handle it
        try:
            from apps.tenancy.models import Membership
            membership = Membership.objects.get(
                organisation=org, user=request.user, is_active=True
            )
            # Owners and admins are never throttled by member limits
            if membership.role in ("owner", "admin"):
                return True
            # Check current plan limit
            sub = getattr(org, "subscription", None)
            if sub is None or not sub.is_active:
                return True
            max_users = sub.plan.features.get("max_users") if sub.plan.features else None
            if not max_users:
                return True
            active_non_owner = Membership.objects.filter(
                organisation=org, is_active=True
            ).exclude(role="owner").count()
            if active_non_owner > int(max_users):
                self.message = (
                    f"Your organisation has exceeded the {max_users}-member limit on its current plan. "
                    "Please ask the account owner to upgrade or deactivate excess members."
                )
                return False
        except Exception:
            pass
        return True


# ─── Per-person module access (H-2) ──────────────────────────────────────────
#
# The owner ticks boxes saying which modules each team member may touch. Those
# ticks were read by the browser — useModuleAccess.ts hides menu items and
# blocks routes — but the server checked only two things: does the ORGANISATION
# pay for the module (plan_requires), and is this person at least `staff`
# (IsStaff). Neither looks at the ticks.
#
# So the ticks were a sign on a door, not a lock. A team member with HR
# unticked still saw the HR menu disappear, and could still ask the server for
# the staff list directly and receive salaries, national ID numbers, pension
# numbers and bank details. Across the whole backend the ticks were consulted
# in exactly one place (invoice editing in apps/sales/views.py).
#
# This mirrors useModuleAccess.ts exactly, deliberately — the browser and the
# server must not disagree about who may see what:
#
#   superuser / owner / admin  → full access, ticks ignored
#   everyone else              → no record means NO access ("restrictive
#                                default for sub-accounts", per that file)
#     none  → nothing
#     view  → read only
#     write → read + create
#     edit  → read + create + change + delete
#
# Safe to enforce: owners and admins bypass entirely, and any member who is
# meant to have narrower access already carries explicit rows.

_READ_METHODS = ("GET", "HEAD", "OPTIONS")
_CREATE_METHODS = ("POST",)


def _effective_module_level(user, org, module_key: str) -> str:
    """The person's access level for one module: "none", "view", "write" or "edit".

    Owners and admins are unrestricted by design (the ticks exist to narrow
    everyone else), so they get "edit". Matches useModuleAccess.ts. Everyone
    else with no record gets "none".
    """
    if has_minimum_role(user, org, "admin"):
        return "edit"

    from apps.tenancy.models import ModulePermission

    membership = user.memberships.filter(organisation=org, is_active=True).first()
    if not membership:
        return "none"
    perm = ModulePermission.objects.filter(
        membership=membership, module=module_key
    ).first()
    return perm.access_level if perm else "none"


def requires_module(module_key: str):
    """
    Permission class factory: gate a viewset on the owner's per-person ticks.

        class EmployeeViewSet(...):
            permission_classes = [IsAuthenticated, IsStaff, requires_module("payroll")]

    Stacks with the role and plan checks rather than replacing them: role says
    how senior you are, plan says what the company bought, this says what you
    personally were granted. All three have to pass.
    """

    class _ModuleAccess(BasePermission):
        message = (
            "You do not have access to this area. Ask an owner or admin to "
            "grant it in Team settings."
        )

        def has_permission(self, request, view):
            user = request.user
            if not user or not user.is_authenticated:
                return False
            if user.is_superuser:
                _get_or_resolve_org(request)
                return True

            org = _get_or_resolve_org(request)
            if not org:
                return False

            level = _effective_module_level(user, org, module_key)

            if level == "none":
                return False
            if request.method in _READ_METHODS:
                return True
            if request.method in _CREATE_METHODS:
                return level in ("write", "edit")
            # PUT / PATCH / DELETE — changing or removing existing records.
            return level == "edit"

    _ModuleAccess.__name__ = f"RequiresModule_{module_key}"
    _ModuleAccess.__qualname__ = _ModuleAccess.__name__
    return _ModuleAccess


# ─── Per-report access (registry reports and legacy report routes) ───────────
#
# A report shows the same data as a normal screen, so it must need the same
# keys as that screen: the owner's tick for the module the data belongs to,
# the role that screen asks for, and the plan the company bought. Holding only
# the "Reports" tick must not let a member read salaries or the ledger.

# Modules whose normal screens also demand a role above staff.
_REPORT_MODULE_MIN_ROLE = {"accounting": "accountant", "tax": "accountant"}
# Modules whose normal screens are behind a plan gate (plan_requires).
_REPORT_MODULE_PLAN = ("accounting", "payroll", "bills", "purchases", "suppliers")


class _ReportAccessContext:
    """Everything needed to judge many reports for ONE request, fetched once.

    The catalog asks about every report; resolving role, ticks and plan per
    report cost ~150-250 queries. Here it is three or four in total.
    """

    def __init__(self, request):
        user = request.user
        self.superuser = bool(user and user.is_authenticated and user.is_superuser)
        self.ok = False          # active member of the resolved organisation
        self.role_level = 0
        self.is_admin = False
        self.levels = {}
        self.org = None
        self._plan_cache = {}
        if not user or not user.is_authenticated:
            return
        if self.superuser:
            self.ok = True
            return
        org = _get_or_resolve_org(request)
        if not org:
            return
        membership = user.memberships.filter(organisation=org, is_active=True).first()
        if not membership:
            return
        from apps.tenancy.models import ModulePermission

        self.org = org
        self.ok = True
        self.role_level = ROLE_HIERARCHY.get(membership.role, 0)
        self.is_admin = self.role_level >= ROLE_HIERARCHY["admin"]
        self.levels = dict(
            ModulePermission.objects.filter(membership=membership)
            .values_list("module", "access_level")
        )

    def plan_ok(self, module_key):
        if module_key not in self._plan_cache:
            self._plan_cache[module_key] = plan_denial(self.org, module_key) is None
        return self._plan_cache[module_key]


def _report_context(request):
    ctx = getattr(request, "_report_access_ctx", None)
    if ctx is None:
        ctx = _ReportAccessContext(request)
        try:
            request._report_access_ctx = ctx
        except AttributeError:  # pragma: no cover - exotic request objects
            pass
    return ctx


def user_can_run_report(request, report_def) -> bool:
    """True when this requester may run the given report (registry or legacy route).

    `report_def` needs `.module`, optional `.also_modules` and optional
    `.owner_admin_only` (cost-bearing reports that the Products screen hides
    from everyone but owners and admins).

    Superusers, owners and admins see everything (they also skip plan gates, as
    before). Everyone else needs: an active membership in the organisation, a
    tick above "none" for the module (and any extra modules), the minimum role
    that module's screens require, and the plan module where one applies.
    """
    ctx = _report_context(request)
    if not ctx.ok:
        return False
    if ctx.superuser or ctx.is_admin:
        return True
    if getattr(report_def, "owner_admin_only", False):
        return False

    modules = (report_def.module,) + tuple(
        getattr(report_def, "also_modules", ()) or ()
    )
    for module_key in modules:
        if ctx.levels.get(module_key, "none") == "none":
            return False
        min_role = _REPORT_MODULE_MIN_ROLE.get(module_key)
        if min_role and ctx.role_level < ROLE_HIERARCHY[min_role]:
            return False
        if module_key in _REPORT_MODULE_PLAN and not ctx.plan_ok(module_key):
            return False
    return True


class RegisterSellingRead(BasePermission):
    """
    Read-only door for the till: a team member who may RING SALES (sales
    module at "write" or "edit") can load the product list and the warehouse
    list the register needs, without the owner ticking Inventory as well.

    Deliberately narrow, so it can be OR-ed next to a viewset's normal rule:
      - only list and detail reads (no stock, movements, low-stock, import,
        export or any other extra action),
      - only for someone who is at least `staff` in the organisation,
      - never any create / change / delete.
    Cost prices stay hidden: the product serializer already strips them for
    anyone who is not an owner or admin. Which organisation's rows come back
    is still decided by the tenant filter on the viewset, not by this class.
    """

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if request.method not in _READ_METHODS:
            return False
        if getattr(view, "action", None) not in ("list", "retrieve"):
            return False
        org = _get_or_resolve_org(request)
        if not org or not has_minimum_role(user, org, "staff"):
            return False

        return _effective_module_level(user, org, "sales") in ("write", "edit")
