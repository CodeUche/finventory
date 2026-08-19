"""
Activate / deactivate the shared demo account used for click-through testing.

WHY THIS EXISTS
    End-to-end click-throughs need a real account on the real deployment. The
    failure mode is not the account existing — it is the account being left
    enabled with a password somebody knows. Doing this by hand invites exactly
    that: activate, test, get distracted, and a standing credential is now live
    on production forever.

    So activation is deliberately disposable. Every activation mints a NEW
    random password, prints it once, and never stores it anywhere else.
    Deactivation restores every lock. There is no state in which this account
    sits enabled with a password that has been written down.

THE FOUR LOCKS (deactivate restores all of them; each alone blocks sign-in)
    is_active = False        SimpleJWT rejects before any password check
    is_verified = False      the email-verification gate refuses independently
    unusable password        Django stores a "!" sentinel — NO password matches
    no staff / superuser     never granted here, and asserted on activation

    The third is the one that makes a leaked password harmless: after
    deactivation the old password is not "the right password to a disabled
    account", it is not a password at all.

USAGE
    python manage.py demo_account --status
    python manage.py demo_account --activate      # prints a fresh password ONCE
    python manage.py demo_account --deactivate    # restores all four locks

    Feed the printed password to the specs through the environment, never a file:
        E2E_RECON_EMAIL=... E2E_RECON_PASSWORD=... npx playwright test --project=bank-recon

NOTES
    * The address lives on a `.test` domain, which is reserved by RFC 2606 and
      not routable — so no password-reset mail can ever be delivered to it, and
      that recovery vector simply does not exist.
    * Refuses outright to touch a staff/superuser account or anything off a
      test domain, so it cannot be pointed at a real customer by accident.
"""
import secrets
import string

from django.core.management.base import BaseCommand, CommandError

DEFAULT_EMAIL = "recon.demo@audity.test"

# Reserved, non-routable domains (RFC 2606 / RFC 6761). Anything else is
# presumed to be a real person and is refused.
ALLOWED_SUFFIXES = (".test", ".local")
ALLOWED_DOMAINS = {"example.com", "example.org", "example.net"}


def _mint_password() -> str:
    """A fresh 24-char password per activation. Long and random enough that it
    never needs to be reused, which is the entire point."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_"
    return "".join(secrets.choice(alphabet) for _ in range(24))


class Command(BaseCommand):
    help = ("Activate (with a freshly minted one-time password) or deactivate "
            "the shared demo account used for click-through testing.")

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--activate", action="store_true",
                           help="Enable the account and print a NEW random password once.")
        group.add_argument("--deactivate", action="store_true",
                           help="Restore all four locks (inactive, unverified, unusable password).")
        group.add_argument("--status", action="store_true",
                           help="Report the account's current lock state without changing it.")
        parser.add_argument("--email", default=DEFAULT_EMAIL,
                            help=f"Target account (default {DEFAULT_EMAIL}). Must be on a test domain.")

    # ── helpers ──────────────────────────────────────────────────────────────

    def _get_user(self, email):
        from apps.authentication.models import User

        email = (email or "").strip().lower()
        domain = email.rsplit("@", 1)[-1] if "@" in email else ""
        if not (domain in ALLOWED_DOMAINS or domain.endswith(ALLOWED_SUFFIXES)):
            raise CommandError(
                f"Refusing to manage '{email}': only reserved test domains are allowed "
                f"({', '.join(sorted(ALLOWED_DOMAINS))}, *{', *'.join(ALLOWED_SUFFIXES)}). "
                "This command must never be pointed at a real account."
            )

        user = User.objects.filter(email=email).first()
        if not user:
            raise CommandError(f"No account found for '{email}'.")
        if user.is_staff or user.is_superuser:
            raise CommandError(
                f"Refusing to manage '{email}': it is a staff/superuser account. "
                "The demo account must never hold elevated privileges."
            )
        return user

    def _report(self, user):
        locked = (
            not user.is_active
            and not user.is_verified
            and not user.has_usable_password()
        )
        self.stdout.write("")
        self.stdout.write(f"  account          : {user.email}")
        self.stdout.write(f"  is_active        : {user.is_active}")
        self.stdout.write(f"  is_verified      : {user.is_verified}")
        self.stdout.write(f"  usable password  : {user.has_usable_password()}")
        self.stdout.write(f"  staff/superuser  : {user.is_staff} / {user.is_superuser}")
        self.stdout.write(
            self.style.SUCCESS("  state            : LOCKED — cannot sign in")
            if locked else
            self.style.WARNING("  state            : ACTIVE — deactivate when the run finishes")
        )
        self.stdout.write("")

    # ── entry point ──────────────────────────────────────────────────────────

    def handle(self, *args, **opts):
        user = self._get_user(opts["email"])

        if opts["status"]:
            self._report(user)
            return

        if opts["deactivate"]:
            user.is_active = False
            user.is_verified = False
            # Order matters: set_unusable_password() only mutates the instance,
            # so it has to happen before the save that persists it.
            user.set_unusable_password()
            user.save(update_fields=["is_active", "is_verified", "password"])
            self.stdout.write(self.style.SUCCESS(f"\nDeactivated {user.email} — all four locks restored."))
            self._report(user)
            return

        # --activate
        password = _mint_password()
        user.is_active = True
        user.is_verified = True
        user.set_password(password)
        user.save(update_fields=["is_active", "is_verified", "password"])

        self.stdout.write(self.style.SUCCESS(f"\nActivated {user.email}"))
        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n  This password is shown ONCE and is not stored anywhere:\n"))
        self.stdout.write(f"      {password}\n")
        self.stdout.write(
            "  Pass it to the specs through the environment, never a file:\n"
            f"      E2E_RECON_EMAIL={user.email} E2E_RECON_PASSWORD='{password}' \\\n"
            "          npx playwright test --project=bank-recon\n"
        )
        self.stdout.write(self.style.WARNING(
            "  Run --deactivate as soon as the run finishes. Until you do, this is a\n"
            "  live credential on a real deployment.\n"))
