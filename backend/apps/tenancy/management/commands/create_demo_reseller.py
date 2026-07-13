"""
Create (or refresh) a time-limited demo account for a reseller / accountant reviewer.

Grants FULL app access + the Partner Agency layer via the `partner-agency` plan,
on a TRIALING subscription that auto-expires after exactly N months (default 1).
After expiry the subscription becomes inactive → SubscriptionActive blocks all
writes and the frontend flips to the billing-only paywall (access cut off).

The account is a normal organisation OWNER — NOT a Django superuser / staff.

Idempotent: re-running with the same --email refreshes the trial window and
re-provisions the partner profile without creating duplicates.

Usage:
    python manage.py create_demo_reseller \
        --email reviewer@example.com --password 'S0meStrongPass!' \
        --org "Demo Accounting Firm" --months 1
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from dateutil.relativedelta import relativedelta


class Command(BaseCommand):
    help = "Create/refresh a demo reseller account with full features + partner agency on a 1-month auto-expiring trial."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--password", required=True)
        parser.add_argument("--first-name", default="Demo")
        parser.add_argument("--last-name", default="Reviewer")
        parser.add_argument("--org", default="Demo Accounting Firm")
        parser.add_argument("--months", type=int, default=1)

    @transaction.atomic
    def handle(self, *args, **opts):
        from apps.authentication.models import User
        from apps.subscriptions.models import Plan, Subscription
        from apps.subscriptions.services import PaystackSubscriptionService
        from apps.tenancy.models import Membership
        from apps.tenancy.services import OrganisationService

        email = opts["email"].strip().lower()
        months = opts["months"]

        try:
            plan = Plan.objects.get(slug="partner-agency")
        except Plan.DoesNotExist:
            raise CommandError("Plan 'partner-agency' not found — run subscription migrations first.")

        # 1. User — normal account, explicitly NOT superuser/staff.
        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "first_name": opts["first_name"],
                "last_name": opts["last_name"],
                "is_verified": True,
                "is_active": True,
            },
        )
        user.set_password(opts["password"])
        user.is_active = True
        user.is_verified = True
        user.is_staff = False
        user.is_superuser = False
        user.must_change_password = False
        user.save()

        # 2. Organisation — owner membership + COA/tax seed + (temporary free plan).
        owner_membership = (
            Membership.objects.filter(user=user, role=Membership.Role.OWNER, is_active=True)
            .select_related("organisation")
            .first()
        )
        if owner_membership:
            org = owner_membership.organisation
        else:
            org = OrganisationService.create_organisation(
                name=opts["org"],
                owner=user,
                extra={"country": "NG", "currency": "NGN", "email": email},
            )

        # 3. Partner-agency plan on a TRIALING subscription, expiring in exactly N months.
        now = timezone.now()
        expires = now + relativedelta(months=months)
        sub = getattr(org, "subscription", None)
        if sub is None:
            sub = Subscription.objects.create(
                plan=plan,
                status=Subscription.Status.TRIALING,
                trial_end=expires,
                current_period_start=now,
                current_period_end=expires,
            )
            org.subscription = sub
            org.save(update_fields=["subscription"])
        else:
            sub.plan = plan
            sub.status = Subscription.Status.TRIALING
            sub.trial_end = expires
            sub.current_period_start = now
            sub.current_period_end = expires
            sub.canceled_at = None
            sub.save()

        if not org.onboarding_completed:
            org.onboarding_completed = True
            org.save(update_fields=["onboarding_completed"])

        # 4. Provision the Partner Agency profile (tier=agency, unlimited clients).
        PaystackSubscriptionService._provision_partner_profile(org, plan)

        # 5. Report.
        self.stdout.write(self.style.SUCCESS("=== DEMO RESELLER ACCOUNT READY ==="))
        self.stdout.write(f"  User created:     {created}")
        self.stdout.write(f"  Email:            {email}")
        self.stdout.write(f"  Password:         {opts['password']}")
        self.stdout.write(f"  Organisation:     {org.name} ({org.id})")
        self.stdout.write(f"  Role:             owner (superuser={user.is_superuser}, staff={user.is_staff})")
        self.stdout.write(f"  Plan:             {plan.name} [{plan.slug}] — TRIALING")
        self.stdout.write(f"  Partner agency:   provisioned (tier=agency)")
        self.stdout.write(f"  Access starts:    {now.isoformat()}")
        self.stdout.write(f"  Auto-expires:     {expires.isoformat()}  ({months} month(s))")
        self.stdout.write(self.style.WARNING("  After expiry: writes blocked + billing-only paywall (access cut off)."))
