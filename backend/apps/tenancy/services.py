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

from django.db import IntegrityError, connection, transaction
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
        org_id = uuid.uuid4()
        base_slug = OrganisationService._base_slug(name)

        # Wrap org + membership in a single atomic block so a crash between the
        # two INSERTs cannot leave an orphaned org with no membership.
        # Set both RLS GUCs transaction-locally at the START so any active RLS
        # policies on INSERT (membership_insert, org_insert) see the correct
        # context on pgBouncer connections where session-level set_config is lost.
        with transaction.atomic():
            from apps.core.middleware import _is_postgres
            if _is_postgres():
                with connection.cursor() as _cur:
                    _cur.execute(
                        "SELECT set_config('app.current_org_id', %s, TRUE)", [str(org_id)]
                    )
                    _cur.execute(
                        "SELECT set_config('app.current_user_id', %s, TRUE)", [str(owner.pk)]
                    )

            # Retry slug on IntegrityError — the ORM slug-existence check can be
            # blocked by RLS (the existing org is invisible under a different context),
            # so we let the DB's unique constraint be the authoritative collision
            # detector and generate a random-hex suffix on conflict.
            slug = base_slug
            for _attempt in range(6):
                try:
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
                    break
                except IntegrityError as exc:
                    if "slug" not in str(exc) or _attempt >= 5:
                        raise
                    slug = f"{base_slug}-{secrets.token_hex(2)}"
                    logger.warning(
                        "create_organisation: slug '%s' conflict, retrying with '%s'",
                        base_slug if _attempt == 0 else slug, slug,
                    )

            Membership.objects.create(
                user=owner,
                organisation=org,
                role=Membership.Role.OWNER,
                is_active=True,
                joined_at=timezone.now(),
            )

        # Seeding runs AFTER the atomic block above has committed, so the
        # transaction-local GUCs set at line 59 are already gone by now. The
        # connection is back on the SENTINEL org, which matches no row, so every
        # INSERT below was refused by the RLS WITH CHECK clause and every failure
        # was swallowed by the seeders' own try/except as a warning. New
        # organisations got no chart of accounts, no tax config and no WHT rates,
        # silently, and landed on an empty account picker. See NEW-18.
        #
        # organisation_context sets app.current_org_id at SESSION level, which is
        # what RLSMiddleware does for ordinary requests and is therefore known to
        # hold on this deployment's connections. Session level also means no
        # transaction is involved: each seeder keeps its own try/except and stays
        # independent, so one failing cannot poison a shared transaction and take
        # the rest down with it.
        #
        # It restores the SENTINEL on exit — including if a seeder raises — which
        # is exactly the value the middleware left here during signup, so nothing
        # downstream sees a changed context.
        from apps.core.tenant_context import organisation_context

        with organisation_context(org.id):
            # Auto-assign the Free plan so all features are available immediately
            OrganisationService._assign_free_plan(org)

            # Seed chart of accounts so accounting module is ready from day 1 (non-fatal)
            OrganisationService._seed_chart_of_accounts(org)

            # Auto-create GL account mapping based on seeded COA (non-fatal)
            OrganisationService._seed_account_mapping(org)

            # Seed country-specific default tax configuration (non-fatal)
            OrganisationService._seed_tax_config(org)

            # Seed WHT 2024 Regulation rates for Nigerian orgs (non-fatal)
            OrganisationService._seed_wht_rates(org)

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

    @staticmethod
    def _seed_account_mapping(org: Organisation) -> None:
        """Auto-create and fill GL account mapping based on seeded COA."""
        try:
            from apps.accounting.services import AccountMappingService
            AccountMappingService.get_or_create_mapping(org)
            logger.info("Account mapping seeded for org %s", org.id)
        except Exception as exc:
            logger.warning("Could not seed account mapping for org %s: %s", org.id, exc)

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

    # WHT 2024 Regulation (Deduction of Tax at Source Regulations 2024, eff. 1 Jan 2025)
    # Rates: (transaction_type, company_rate_pct, individual_rate_pct)
    _WHT_2024_RATES_NG = [
        ("Rent",                                   10, 10),
        ("Dividends",                               10, 10),
        ("Interest",                                10, 10),
        ("Royalties",                               10, 10),
        ("Consulting / Professional Fees",          5,  5),
        ("Technical Fees",                          5,  5),
        ("Management Fees",                         5,  5),
        ("Construction (Contract)",                 5,  5),
        ("Agency / Brokerage",                      5,  5),
        ("Architect / Surveyor / Engineer Fees",    5,  5),
        ("Commission (Sales/Marketing)",            5,  5),
        ("Legal / Audit Fees",                      5,  5),
        ("Director Fees",                           10, 10),
        ("Hire of Equipment / Vehicles",            5,  5),
        ("Supply of Goods (>₦2m/month)",            2,  5),
        ("Supply of Services (>₦2m/month)",         2,  5),
        ("Inland Freight",                          5,  5),
    ]

    @staticmethod
    def _seed_wht_rates(org: Organisation) -> None:
        """Seed Nigeria WHT 2024 Regulation rates on org creation (NG only, idempotent)."""
        if org.country != "NG":
            return
        try:
            from apps.tax.models import WHTRate
            for (transaction_type, company_rate, individual_rate) in OrganisationService._WHT_2024_RATES_NG:
                WHTRate.objects.get_or_create(
                    organisation=org,
                    transaction_type=transaction_type,
                    defaults={
                        "company_rate": company_rate,
                        "individual_rate": individual_rate,
                        "is_active": True,
                    },
                )
            logger.info("WHT 2024 rates seeded for org %s", org.id)
        except Exception as exc:
            logger.warning("Could not seed WHT rates for org %s: %s", org.id, exc)

    @staticmethod
    def invite_member(organisation, email: str, role: str, invited_by, module_permissions: dict = None) -> Invitation:
        """Create a pending invitation and send the invitee an email. Expires in 7 days."""
        invitation = Invitation.objects.create(
            organisation=organisation,
            email=email,
            role=role,
            invited_by=invited_by,
            expires_at=timezone.now() + timedelta(days=7),
            module_permissions=module_permissions or {},
        )
        OrganisationService._send_invitation_email(invitation)
        logger.info("Invitation created for %s to org %s", email, organisation.id)
        return invitation

    @staticmethod
    def _send_invitation_email(invitation: Invitation) -> None:
        """Send the invitation email with accept / reject links."""
        try:
            from django.conf import settings as django_settings
            from django.core.mail import send_mail
            from django.utils.html import escape

            inviter_name = (
                f"{invitation.invited_by.first_name} {invitation.invited_by.last_name}".strip()
                or invitation.invited_by.email
            )
            frontend_url = getattr(django_settings, "FRONTEND_URL", "http://localhost:5173")
            # Token is a UUID — safe to embed directly in URLs
            token = str(invitation.token)
            accept_url = f"{frontend_url}/accept-invite/{token}"
            reject_url = f"{frontend_url}/reject-invite/{token}"

            # Escape all user-controlled strings before embedding in HTML
            safe_inviter = escape(inviter_name)
            safe_org = escape(invitation.organisation.name)
            safe_role = escape(invitation.role)

            subject = f"You've been invited to join {invitation.organisation.name} on Audity"
            plain = (
                f"Hi,\n\n"
                f"{inviter_name} has invited you to join {invitation.organisation.name} "
                f"as {invitation.role} on Audity.\n\n"
                f"Accept: {accept_url}\n"
                f"Decline: {reject_url}\n\n"
                f"This invitation expires in 7 days.\n"
                f"If you did not expect this email you can safely ignore it.\n"
            )
            html = f"""<!DOCTYPE html>
<html>
<body style="font-family:sans-serif;background:#f1f5f9;padding:24px;">
  <div style="max-width:500px;margin:auto;background:#fff;border-radius:12px;padding:32px;">
    <h2 style="color:#f97316;margin-top:0;">You&rsquo;re invited to Audity</h2>
    <p><strong>{safe_inviter}</strong> has invited you to join
       <strong>{safe_org}</strong> as <strong>{safe_role}</strong>.</p>
    <div style="margin:28px 0;">
      <a href="{accept_url}"
         style="display:inline-block;background:#f97316;color:#fff;text-decoration:none;
                padding:12px 24px;border-radius:8px;font-weight:600;margin-right:12px;">
        Accept Invitation
      </a>
      <a href="{reject_url}"
         style="display:inline-block;background:#e2e8f0;color:#64748b;text-decoration:none;
                padding:12px 24px;border-radius:8px;font-weight:600;">
        Decline
      </a>
    </div>
    <p style="color:#94a3b8;font-size:12px;">
      This invitation expires in 7 days.
      If you did not expect this email, you can safely ignore it.
    </p>
  </div>
</body>
</html>"""
            from_email = getattr(django_settings, "DEFAULT_FROM_EMAIL", None) or "noreply@audity.app"
            send_mail(subject, plain, from_email, [invitation.email], html_message=html, fail_silently=True)
        except Exception as exc:
            logger.warning("Could not send invitation email to %s: %s", invitation.email, exc)

    @staticmethod
    def reject_invitation(token: str) -> None:
        """Mark an invitation as rejected by the invitee."""
        try:
            invitation = Invitation.objects.get(
                token=token,
                is_consumed=False,
                is_rejected=False,
                expires_at__gte=timezone.now(),
            )
            invitation.is_rejected = True
            invitation.save(update_fields=["is_rejected"])
            logger.info("Invitation %s rejected", token)
        except Invitation.DoesNotExist:
            pass

    @staticmethod
    def accept_invitation(invitation: Invitation, user) -> Membership:
        """Accept an invitation, creating or reactivating membership with optional per-module permissions."""
        from .models import ModulePermission
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

        # Apply granular module permissions if specified on the invitation
        if invitation.module_permissions:
            ModulePermission.objects.filter(membership=membership).delete()
            for module, level in invitation.module_permissions.items():
                ModulePermission.objects.create(
                    membership=membership,
                    module=module,
                    access_level=level,
                )

        invitation.is_consumed = True
        invitation.save(update_fields=["is_consumed"])

        logger.info("User %s joined org %s as %s", user.id, invitation.organisation.id, invitation.role)
        return membership

    @staticmethod
    def _base_slug(name: str) -> str:
        """Derive the base slug from an organisation name.

        Strips common business noise words (Ltd, PLC, Inc…) so that "Acme Ltd"
        and "Acme Limited" share the same normalised base.  Collision resolution
        (appending a random hex suffix) is handled at INSERT time in
        create_organisation() rather than here, because an ORM existence-check
        can be blocked by RLS and incorrectly report a taken slug as free.
        """
        cleaned = _BUSINESS_NOISE.sub("", name).strip()
        base = slugify(cleaned)[:80].strip("-")
        if not base:
            base = slugify(name)[:80]
        return base or "org"
