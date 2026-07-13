"""
Instantly revoke (or restore) a demo/reviewer account's access.

Deactivating the user (`is_active=False`) is a true, immediate cutoff:
  - SimpleJWT's login backend rejects inactive users → they cannot log in.
  - JWTAuthentication rejects any token they already hold → existing sessions die.
This works regardless of where the frontend is hosted (Vercel, desktop, scripts),
because it revokes at the backend/account level, not the frontend.

Reversible: `--reactivate` restores access.

Usage:
    python manage.py revoke_demo_reseller --email reviewer@example.com
    python manage.py revoke_demo_reseller --email reviewer@example.com --reactivate
    python manage.py revoke_demo_reseller --email reviewer@example.com --cancel-subscription
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone


class Command(BaseCommand):
    help = "Revoke (deactivate) or restore a demo/reviewer account. Cuts off login + existing tokens."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument(
            "--reactivate", action="store_true",
            help="Restore access instead of revoking it.",
        )
        parser.add_argument(
            "--cancel-subscription", action="store_true",
            help="Also mark the owned org's subscription CANCELED (belt-and-suspenders).",
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        from apps.authentication.models import User
        from apps.subscriptions.models import Subscription
        from apps.tenancy.models import Membership

        email = opts["email"].strip().lower()
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise CommandError(f"No user with email {email!r}.")

        if user.is_superuser:
            raise CommandError("Refusing to modify a superuser account.")

        reactivate = opts["reactivate"]
        user.is_active = reactivate
        user.save(update_fields=["is_active"])

        if opts["cancel_subscription"]:
            memberships = Membership.objects.filter(
                user=user, role=Membership.Role.OWNER
            ).select_related("organisation")
            for m in memberships:
                sub = getattr(m.organisation, "subscription", None)
                if sub is not None:
                    if reactivate:
                        sub.status = Subscription.Status.TRIALING
                        sub.canceled_at = None
                    else:
                        sub.status = Subscription.Status.CANCELED
                        sub.canceled_at = timezone.now()
                    sub.save(update_fields=["status", "canceled_at", "updated_at"])

        action = "RESTORED" if reactivate else "REVOKED"
        self.stdout.write(self.style.SUCCESS(f"=== ACCESS {action} ==="))
        self.stdout.write(f"  Email:      {email}")
        self.stdout.write(f"  is_active:  {user.is_active}")
        if not reactivate:
            self.stdout.write(self.style.WARNING(
                "  Login blocked and any existing tokens are now rejected."
            ))
