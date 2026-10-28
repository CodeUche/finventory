"""
One self-approval rule for every document that needs sign-off.

    You can approve your own item only when nobody else can approve it.

Why one rule: bills refused self-approval outright (so a one-person business
could never approve a bill, including the bills raised from purchase-order
deliveries), manual journals allowed it outright (the riskiest document, with
no control at all), and payroll only checked "whoever submitted". See
decision OBS-20 in the 2026-10-02 QA report.

An "approver" is an active owner or admin of the organisation. When someone
else holds that role, approval must come from them. When the creator is the
only approver, they may approve their own item; the approval is written to the
audit log as a sole-approver self-approval so an accountant can see it.
"""

SELF_APPROVED_NOTE = "Self-approved (sole approver)"


def other_approvers(organisation, user):
    """Active owners/admins of `organisation` other than `user`."""
    from apps.tenancy.models import Membership

    return list(
        Membership.objects.filter(
            organisation=organisation, is_active=True, role__in=("owner", "admin"),
        ).exclude(user=user).select_related("user")
    )


def check_approval(organisation, creator, approver, what, *, object_id="", model_name="", request=None):
    """
    Raise ValueError if `approver` may not approve `what` (e.g. "bill").
    Returns True when this is a sole-approver self-approval (already audit
    logged), False for an ordinary approval by someone other than the creator.
    """
    if creator is None or creator != approver:
        return False

    others = other_approvers(organisation, approver)
    if others:
        names = ", ".join(
            (m.user.get_full_name() or m.user.email) for m in others[:3]
        )
        raise ValueError(
            f"You created this {what}, and another person can approve it. "
            f"Ask {names} to approve it."
        )

    try:
        from apps.core.models import AuditLog

        AuditLog.log(
            action=AuditLog.UPDATE, user=approver, organisation=organisation,
            model_name=model_name or what.title(), object_id=str(object_id),
            object_repr=SELF_APPROVED_NOTE,
            changes={"approval": {"old": None, "new": SELF_APPROVED_NOTE}},
            request=request,
        )
    except Exception:
        pass
    return True
