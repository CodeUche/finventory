"""
Tenancy service layer.

Business logic for organisation creation, invitations, and membership management.
Keeps views thin and logic testable in isolation.
"""

import logging
import re
import secrets
import uuid
from datetime import timedelta

from django.utils import timezone
from django.utils.text import slugify

# Common business-type words that inflate org names but carry no uniqueness.
# Stripping them before slugifying means "Acme Ltd" and "Acme Limited" share
# the same normalised base and cannot silently collide into near-identical slugs.
_BUSINESS_NOISE = re.compile(
    r'\b(ltd|limited|plc|inc|incorporated|llc|llp|co|corp|corporation|company|'
    r'enterprises?|services?|solutions?|group|holdings?|associates?|partners?|'
    r'international|global|africa|african|ng|nig|nigeria|nigerian)\b',
    re.IGNORECASE,
)

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

        # Pre-generate the org UUID and set the RLS context variable BEFORE the
        # INSERT so the tenant_isolation WITH CHECK (id = current_org_id) clause
        # evaluates as (new_uuid = new_uuid) → true.  Without this, the INSERT
        # runs under SENTINEL and the WITH CHECK rejects it with an RLS violation.
        org_id = uuid.uuid4()
        try:
            from apps.core.middleware import _set_org, _set_user
            _set_org(str(org_id))
            _set_user(str(owner.pk))
        except Exception:
            pass

        org = Organisation.objects.create(
            id=org_id,
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

        # Seed chart of accounts so accounting module is ready from day 1 (non-fatal)
        OrganisationService._seed_chart_of_accounts(org)

        # Seed country-specific default tax configuration (non-fatal)
        OrganisationService._seed_tax_config(org)

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
    def _seed_chart_of_accounts(org: Organisation) -> None:
        """
        Seed the standard chart of accounts for a new organisation.

        Uses AccountingService.seed_chart_of_accounts which is idempotent
        (get_or_create — safe to call multiple times).
        """
        try:
            from apps.accounting.services import AccountingService
            AccountingService.seed_chart_of_accounts(org)
            logger.info("Chart of accounts seeded for org %s", org.id)
        except Exception as exc:
            logger.warning("Could not seed chart of accounts for org %s: %s", org.id, exc)

    # ─── Tax seed data ────────────────────────────────────────────────────────
    # Each entry: { name, tax_type, is_progressive, flat_rate, personal_allowance, brackets }
    # Brackets: (lower_bound, upper_bound_or_None, rate_pct, cumulative_tax_below)
    _TAX_PRESETS = {
        "NG": [
            {
                "name": "Nigeria Personal Income Tax",
                "tax_type": "income",
                "is_progressive": True,
                "flat_rate": 0,
                "personal_allowance": 200000,
                "brackets": [
                    (0,         300000,  7,    0),
                    (300000,    600000,  11,   21000),
                    (600000,    1100000, 15,   54000),
                    (1100000,   1600000, 19,   129000),
                    (1600000,   3200000, 21,   224000),
                    (3200000,   None,    24,   560000),
                ],
            },
            {
                "name": "Nigeria Corporate Income Tax",
                "tax_type": "corporate",
                "is_progressive": False,
                "flat_rate": 30,
                "personal_allowance": 0,
                "brackets": [],
            },
        ],
        "GH": [
            {
                "name": "Ghana Personal Income Tax",
                "tax_type": "income",
                "is_progressive": True,
                "flat_rate": 0,
                "personal_allowance": 4380,
                "brackets": [
                    (0,      1320,    5,    0),
                    (1320,   2880,    10,   66),
                    (2880,   36600,   17,   222),
                    (36600,  240000,  25,   6053),
                    (240000, None,    35,   56953),
                ],
            },
            {
                "name": "Ghana Corporate Income Tax",
                "tax_type": "corporate",
                "is_progressive": False,
                "flat_rate": 25,
                "personal_allowance": 0,
                "brackets": [],
            },
        ],
        "KE": [
            {
                "name": "Kenya Personal Income Tax (PAYE)",
                "tax_type": "income",
                "is_progressive": True,
                "flat_rate": 0,
                "personal_allowance": 0,
                "brackets": [
                    (0,      288000,  10, 0),
                    (288000, 388000,  25, 28800),
                    (388000, 6000000, 30, 53800),
                    (6000000, None,   35, 1737400),
                ],
            },
            {
                "name": "Kenya Corporate Income Tax",
                "tax_type": "corporate",
                "is_progressive": False,
                "flat_rate": 30,
                "personal_allowance": 0,
                "brackets": [],
            },
        ],
        "ZA": [
            {
                "name": "South Africa Personal Income Tax",
                "tax_type": "income",
                "is_progressive": True,
                "flat_rate": 0,
                "personal_allowance": 91250,
                "brackets": [
                    (0,        237100,  18, 0),
                    (237100,   370500,  26, 42678),
                    (370500,   512800,  31, 77362),
                    (512800,   673000,  36, 121475),
                    (673000,   857900,  39, 179147),
                    (857900,   1817000, 41, 251258),
                    (1817000,  None,    45, 644489),
                ],
            },
            {
                "name": "South Africa Corporate Income Tax",
                "tax_type": "corporate",
                "is_progressive": False,
                "flat_rate": 27,
                "personal_allowance": 0,
                "brackets": [],
            },
        ],
        "GB": [
            {
                "name": "UK Income Tax",
                "tax_type": "income",
                "is_progressive": True,
                "flat_rate": 0,
                "personal_allowance": 12570,
                "brackets": [
                    (0,      37700, 20, 0),
                    (37700,  125140, 40, 7540),
                    (125140, None,   45, 42028),
                ],
            },
            {
                "name": "UK Corporation Tax",
                "tax_type": "corporate",
                "is_progressive": False,
                "flat_rate": 25,
                "personal_allowance": 0,
                "brackets": [],
            },
        ],
    }

    @staticmethod
    def _seed_tax_config(org: Organisation) -> None:
        """Seed country-specific default tax configurations on org creation."""
        try:
            from datetime import date
            from apps.tax.models import TaxBracket, TaxConfig
            from decimal import Decimal

            presets = OrganisationService._TAX_PRESETS.get(org.country, [])
            if not presets:
                return

            current_year = date.today().year
            for preset in presets:
                config, created = TaxConfig.objects.get_or_create(
                    organisation=org,
                    name=preset["name"],
                    tax_year=current_year,
                    defaults={
                        "tax_type": preset["tax_type"],
                        "country": org.country,
                        "is_progressive": preset["is_progressive"],
                        "flat_rate": Decimal(str(preset["flat_rate"])),
                        "personal_allowance": Decimal(str(preset["personal_allowance"])),
                        "is_active": True,
                    },
                )
                if created:
                    for (lower, upper, rate, cum) in preset["brackets"]:
                        TaxBracket.objects.create(
                            config=config,
                            lower_bound=Decimal(str(lower)),
                            upper_bound=Decimal(str(upper)) if upper is not None else None,
                            rate=Decimal(str(rate)),
                            cumulative_tax_below=Decimal(str(cum)),
                        )
            logger.info("Tax config seeded for org %s (country=%s)", org.id, org.country)
        except Exception as exc:
            logger.warning("Could not seed tax config for org %s: %s", org.id, exc)

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
        """Generate a unique, non-enumerable slug from the organisation name.

        Steps:
        1. Strip common business-type noise words (Ltd, Limited, PLC, Inc…)
           so that "Acme Ltd" and "Acme Limited" produce the same base slug
           and cannot silently occupy near-identical workspace IDs.
        2. If the normalised base is already taken, append a cryptographically
           random 4-char hex tag (e.g. "acme-3f9a") instead of a predictable
           counter, making workspace IDs unguessable and clearly distinct.
        """
        cleaned = _BUSINESS_NOISE.sub("", name).strip()
        base_slug = slugify(cleaned)[:80].strip("-")
        # Fallback: if stripping left nothing (name was all noise words), use raw name
        if not base_slug:
            base_slug = slugify(name)[:80]

        if not Organisation.objects.filter(slug=base_slug).exists():
            return base_slug

        # Collision resolution — random hex tag, never a predictable counter
        for _ in range(20):
            candidate = f"{base_slug}-{secrets.token_hex(2)}"
            if not Organisation.objects.filter(slug=candidate).exists():
                return candidate

        # Ultra-rare fallback (astronomically unlikely after 20 tries)
        return f"{base_slug}-{secrets.token_hex(4)}"
