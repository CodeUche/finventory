"""
Tenancy signals — cascade sub-account deactivation when an org is deleted/deactivated.

Rule: sub-account users (is_sub_account=True) exist solely to operate within a single
organisation. If that organisation is deactivated (is_active → False) or soft-deleted,
or if the owner's user account is deactivated, sub-accounts must also be blocked
immediately so they cannot log in.

Deactivation vs deletion:
  - Organisation.is_active set to False → deactivate all sub-account User records
    in that org (is_active=False). Memberships are already scoped to org; setting
    the user inactive blocks login at the authentication layer.
  - Organisation soft-deleted (is_deleted=True) → same deactivation.
  - Owner User.is_active set to False → deactivate all sub-accounts across all orgs
    where this user is OWNER (they control those orgs' access).
"""

import logging

from django.db.models.signals import pre_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(pre_save, sender="tenancy.Organisation")
def cascade_org_deactivation_to_subaccounts(sender, instance, **kwargs):
    """
    When an Organisation is deactivated (is_active → False) or soft-deleted
    (is_deleted → True), deactivate all sub-account users in that org.
    """
    if not instance.pk:
        return  # New org — nothing to cascade

    try:
        previous = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        return

    becoming_inactive = previous.is_active and not instance.is_active
    becoming_deleted = not previous.is_deleted and instance.is_deleted

    if not (becoming_inactive or becoming_deleted):
        return

    _deactivate_subaccounts_in_org(instance)


def _deactivate_subaccounts_in_org(org):
    """
    Deactivate all is_sub_account=True users who are members of this org
    and have no active membership in any other org.

    Sub-accounts created via create_subaccount have email = username@org_slug,
    so they are effectively tied to this single organisation. We deactivate
    their User record (is_active=False) so they cannot log in anywhere.
    """
    from django.contrib.auth import get_user_model
    from .models import Membership

    User = get_user_model()

    # Find sub-account user IDs with a membership in this org
    sub_ids = list(
        Membership.objects.filter(
            organisation=org,
            user__is_sub_account=True,
        ).values_list("user_id", flat=True)
    )

    if not sub_ids:
        return

    # Deactivate + revoke memberships
    deactivated = User.objects.filter(
        id__in=sub_ids, is_sub_account=True
    ).update(is_active=False)

    Membership.objects.filter(
        organisation=org, user_id__in=sub_ids
    ).update(is_active=False)

    logger.warning(
        "Cascaded deactivation: %d sub-account(s) deactivated because org '%s' (id=%s) was %s.",
        deactivated,
        org.name,
        org.id,
        "soft-deleted" if org.is_deleted else "deactivated",
    )


@receiver(pre_save, sender="authentication.User")
def cascade_owner_deactivation_to_subaccounts(sender, instance, **kwargs):
    """
    When an owner's User account is deactivated (is_active → False),
    deactivate all sub-account users across every org where this user is OWNER.
    """
    if not instance.pk:
        return  # New user

    try:
        previous = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        return

    becoming_inactive = previous.is_active and not instance.is_active
    if not becoming_inactive:
        return

    from .models import Membership, Organisation

    # Find all orgs where this user is an active owner
    owned_org_ids = list(
        Membership.objects.filter(
            user=instance,
            role=Membership.Role.OWNER,
            is_active=True,
        ).values_list("organisation_id", flat=True)
    )

    if not owned_org_ids:
        return

    orgs = Organisation.objects.filter(id__in=owned_org_ids)
    for org in orgs:
        _deactivate_subaccounts_in_org(org)
