"""
Tenancy service layer.

Business logic for organisation creation, invitations, and membership management.
Keeps views thin and logic testable in isolation.
"""

import logging
from datetime import timedelta

from django.utils import timezone
from django.utils.text import slugify

from .models import Invitation, Membership, Organisation

logger = logging.getLogger(__name__)


class OrganisationService:

    @staticmethod
    def create_organisation(name: str, owner, extra: dict = None) -> Organisation:
        """
        Create a new organisation and grant OWNER role to the creator.

        Args:
            name: Organisation display name.
            owner: User instance who becomes the owner.
            extra: Additional fields (country, currency, etc.)
        """
        extra = extra or {}
        slug = OrganisationService._unique_slug(name)

        org = Organisation.objects.create(
            name=name,
            slug=slug,
            owner=owner,
            account_type=extra.get("account_type", Organisation.AccountType.BUSINESS),
            country=extra.get("country", "NG"),
            currency=extra.get("currency", "NGN"),
            registration_number=extra.get("registration_number", ""),
            tax_id=extra.get("tax_id", ""),
            phone=extra.get("phone", ""),
            email=extra.get("email", ""),
        )

        Membership.objects.create(
            user=owner,
            organisation=org,
            role=Membership.Role.OWNER,
            is_active=True,
            joined_at=timezone.now(),
        )

        # Auto-assign the Free plan so all features are available immediately
        OrganisationService._assign_free_plan(org)

        logger.info("Organisation created: %s (owner=%s)", org.id, owner.id)
        return org

    @staticmethod
    def _assign_free_plan(org: Organisation) -> None:
        """Assign the Free plan subscription to a newly created organisation."""
        try:
            from apps.subscriptions.models import Plan, Subscription

            free_plan = Plan.objects.get(slug="free")
            sub = Subscription.objects.create(
                plan=free_plan,
                status=Subscription.Status.ACTIVE,
                current_period_start=timezone.now(),
                # 100-year period — effectively perpetual for a free plan
                current_period_end=timezone.now() + timedelta(days=36500),
            )
            org.subscription = sub
            org.save(update_fields=["subscription"])
            logger.info("Free plan assigned to org %s", org.id)
        except Exception as exc:
            # Non-fatal: org still works, subscription can be assigned manually
            logger.warning("Could not assign Free plan to org %s: %s", org.id, exc)

    @staticmethod
    def invite_member(organisation, email: str, role: str, invited_by) -> Invitation:
        """Create a pending invitation. Expires in 7 days."""
        invitation = Invitation.objects.create(
            organisation=organisation,
            email=email,
            role=role,
            invited_by=invited_by,
            expires_at=timezone.now() + timedelta(days=7),
        )
        # TODO: Send invitation email via Celery task
        logger.info("Invitation created for %s to org %s", email, organisation.id)
        return invitation

    @staticmethod
    def accept_invitation(invitation: Invitation, user) -> Membership:
        """Accept an invitation, creating or reactivating membership."""
        membership, created = Membership.objects.get_or_create(
            user=user,
            organisation=invitation.organisation,
            defaults={
                "role": invitation.role,
                "invited_by": invitation.invited_by,
                "is_active": True,
                "joined_at": timezone.now(),
            },
        )
        if not created:
            membership.role = invitation.role
            membership.is_active = True
            membership.joined_at = timezone.now()
            membership.save()

        invitation.is_consumed = True
        invitation.save(update_fields=["is_consumed"])

        logger.info("User %s joined org %s as %s", user.id, invitation.organisation.id, invitation.role)
        return membership

    @staticmethod
    def _unique_slug(name: str) -> str:
        """Generate a unique slug from the organisation name."""
        base_slug = slugify(name)[:90]
        slug = base_slug
        counter = 1
        while Organisation.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        return slug
