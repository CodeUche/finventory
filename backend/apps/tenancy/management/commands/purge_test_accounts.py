"""
Delete demo / test user accounts (and the organisations they solely own).

SAFETY MODEL — this command is deliberately conservative:
  * DRY-RUN BY DEFAULT. Nothing is deleted unless you pass --execute.
  * Never touches the protected keep-list: the two reviewer accounts, ANY
    Django superuser or staff user, and the known owner accounts.
  * Only targets emails whose domain looks like a test/demo domain
    (audity.test, test.local, example.com/.org/.net, test.com, mailinator.com,
    or anything ending in `.test` / `.local`). Real personal emails
    (gmail/outlook/company domains) are NEVER auto-targeted — pass them
    explicitly with --email if you really mean it.
  * Refuses to delete more than --max accounts (default 25) unless --force,
    so a bad filter can't wipe the user table.

Usage:
    python manage.py purge_test_accounts                 # dry-run, show what would go
    python manage.py purge_test_accounts --execute       # actually delete
    python manage.py purge_test_accounts --email foo@bar.test --execute
    python manage.py purge_test_accounts --extra-domain sandbox.io --execute
"""
from django.core.management.base import BaseCommand
from django.db import transaction

# Accounts that must survive no matter what.
KEEP_EMAILS = {
    "reseller.reviewer@audity.africa",
    "uiux.reviewer@audity.africa",
    # Owner / operator accounts.
    "ezeprecious.uche@gmail.com",
    "upezeh@outlook.com",
}

# Domains treated as test/demo. `.test` and `.local` are reserved/non-routable
# by RFC, so they are always safe to treat as disposable.
TEST_DOMAINS = {
    "audity.test", "test.local", "example.com", "example.org",
    "example.net", "test.com", "mailinator.com",
}
TEST_SUFFIXES = (".test", ".local")


class Command(BaseCommand):
    help = "Delete demo/test accounts (dry-run by default; --execute to delete). Keeps reviewer/uiux/superuser/owner accounts."

    def add_arguments(self, parser):
        parser.add_argument("--execute", action="store_true",
                            help="Actually delete. Without this the command only reports (dry-run).")
        parser.add_argument("--email", action="append", default=[],
                            help="Also target this exact email (repeatable). Still skipped if on the keep-list.")
        parser.add_argument("--extra-domain", action="append", default=[],
                            help="Also treat this domain as a test domain (repeatable).")
        parser.add_argument("--max", type=int, default=25,
                            help="Safety cap — refuse to delete more than this many unless --force (default 25).")
        parser.add_argument("--force", action="store_true",
                            help="Override the --max safety cap.")

    def handle(self, *args, **opts):
        from apps.authentication.models import User
        try:
            from apps.tenancy.models import Membership, Organisation  # noqa: F401
        except Exception:
            Membership = None

        test_domains = set(TEST_DOMAINS) | {d.strip().lower() for d in opts["extra_domain"]}
        explicit = {e.strip().lower() for e in opts["email"]}

        def is_target(u):
            email = (u.email or "").strip().lower()
            if email in KEEP_EMAILS:
                return False
            if u.is_superuser or u.is_staff:
                return False
            if email in explicit:
                return True
            domain = email.rsplit("@", 1)[-1] if "@" in email else ""
            if domain in test_domains:
                return True
            return any(domain.endswith(s) for s in TEST_SUFFIXES)

        targets = [u for u in User.objects.all().order_by("email") if is_target(u)]

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n{'DELETE' if opts['execute'] else 'DRY-RUN'} — {len(targets)} account(s) matched\n"))
        if not targets:
            self.stdout.write("Nothing to do — no test/demo accounts matched the filter.")
            return

        for u in targets:
            owned = ""
            if Membership is not None:
                orgs = list(
                    Organisation.objects.filter(memberships__user=u, memberships__role="owner")
                    .values_list("name", flat=True)
                )
                if orgs:
                    owned = "  owns: " + ", ".join(orgs)
            self.stdout.write(f"  - {u.email:<40} active={u.is_active}{owned}")

        if not opts["execute"]:
            self.stdout.write(self.style.WARNING(
                "\nDry-run only. Re-run with --execute to delete these accounts."))
            return

        if len(targets) > opts["max"] and not opts["force"]:
            self.stdout.write(self.style.ERROR(
                f"\nRefusing to delete {len(targets)} accounts (> --max {opts['max']}). "
                f"Re-check the filter, or pass --force if this is intended."))
            return

        deleted, failed = 0, []
        for u in targets:
            try:
                with transaction.atomic():
                    email = u.email
                    u.delete()
                    deleted += 1
                    self.stdout.write(self.style.SUCCESS(f"  deleted {email}"))
            except Exception as e:  # keep going; report the ones that couldn't be removed
                failed.append((u.email, f"{type(e).__name__}: {e}"))
                self.stdout.write(self.style.ERROR(f"  FAILED  {u.email} — {type(e).__name__}: {e}"))

        self.stdout.write(self.style.MIGRATE_HEADING(f"\nDone — {deleted} deleted, {len(failed)} failed."))
        if failed:
            self.stdout.write("Failures (likely FK-protected related data — clean those first):")
            for email, err in failed:
                self.stdout.write(f"  - {email}: {err}")
