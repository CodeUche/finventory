"""
Management command: run_firs_sandbox_tests

Runs the FIRS sandbox certification batches for an organisation directly from
the command line.  Useful for:
  - Initial certification before production go-live
  - Verifying sandbox credentials are working after a key rotation
  - Debugging specific failure modes

Usage
=====
    # Run 50 pass tests for a specific org
    python manage.py run_firs_sandbox_tests --org <uuid> --mode pass

    # Run 50 fail tests
    python manage.py run_firs_sandbox_tests --org <uuid> --mode fail

    # Run both in sequence
    python manage.py run_firs_sandbox_tests --org <uuid> --mode both

    # Custom count (e.g. a quick smoke test of 5)
    python manage.py run_firs_sandbox_tests --org <uuid> --mode pass --count 5

Output
======
    Prints a summary table including how many submissions succeeded/failed and
    the cumulative progress toward the 50+50 FIRS requirement.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.einvoicing.models import FirsConfig
from apps.einvoicing.sandbox_runner import SandboxTestRunner, REQUIRED_PASS_COUNT, REQUIRED_FAIL_COUNT


class Command(BaseCommand):
    help = "Run FIRS sandbox certification batches (50 pass + 50 fail requirement)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--org",
            required=True,
            metavar="UUID",
            help="UUID of the Organisation whose FirsConfig to use.",
        )
        parser.add_argument(
            "--mode",
            choices=["pass", "fail", "both"],
            default="both",
            help="Which batch to run: pass, fail, or both (default: both).",
        )
        parser.add_argument(
            "--count",
            type=int,
            default=50,
            help=f"Number of submissions per batch (default: 50; FIRS requires {REQUIRED_PASS_COUNT}+{REQUIRED_FAIL_COUNT}).",
        )

    def handle(self, *args, **options):
        org_id = options["org"]
        mode = options["mode"]
        count = options["count"]

        # Load and validate the FirsConfig
        try:
            config = FirsConfig.objects.select_related("organisation").get(
                organisation_id=org_id
            )
        except FirsConfig.DoesNotExist:
            raise CommandError(
                f"No FirsConfig found for organisation {org_id}. "
                "Check the UUID and ensure the org has a FirsConfig record."
            )

        if not config.use_sandbox:
            raise CommandError(
                "FirsConfig.use_sandbox is False for this org. "
                "Sandbox tests must be run in sandbox mode. "
                "Set use_sandbox=True via the FIRS settings tab before running."
            )

        if not config.app_api_key:
            raise CommandError(
                "No DigiTax API key configured for this org. "
                "Set the API key in the FIRS settings tab before running sandbox tests."
            )

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"\nFIRS Sandbox Certification — Org: {config.organisation.name}"
            )
        )
        self.stdout.write(f"  TIN          : {config.tin or '(not set)'}")
        self.stdout.write(f"  Business name: {config.business_name or '(not set)'}")
        self.stdout.write(f"  Mode         : {mode}")
        self.stdout.write(f"  Count/batch  : {count}")
        self.stdout.write("")

        runner = SandboxTestRunner(config)

        # ── Pass batch ───────────────────────────────────────────────────────
        if mode in ("pass", "both"):
            self.stdout.write(self.style.MIGRATE_LABEL("Running pass batch..."))
            result = runner.run_pass_batch(count=count)
            self.stdout.write(
                f"  Submitted  : {result['submitted']}/{count}"
            )
            self.stdout.write(
                f"  Errors     : {result['errors']}"
            )
            self.stdout.write(
                f"  Run ID     : {result['run_id']}"
            )
            if result["errors"]:
                self.stdout.write(
                    self.style.WARNING(
                        f"  {result['errors']} pass tests failed unexpectedly — "
                        "check FirsSubmission records for error_detail."
                    )
                )
            else:
                self.stdout.write(self.style.SUCCESS("  Pass batch complete."))
            self.stdout.write("")

        # ── Fail batch ───────────────────────────────────────────────────────
        if mode in ("fail", "both"):
            self.stdout.write(self.style.MIGRATE_LABEL("Running fail batch..."))
            result = runner.run_fail_batch(count=count)
            self.stdout.write(
                f"  Triggered errors   : {result['triggered_errors']}/{count}"
            )
            self.stdout.write(
                f"  Unexpected passes  : {result['unexpected_passes']}"
            )
            self.stdout.write(
                f"  Run ID             : {result['run_id']}"
            )
            if result["unexpected_passes"]:
                self.stdout.write(
                    self.style.WARNING(
                        f"  {result['unexpected_passes']} fail tests were unexpectedly accepted — "
                        "the invalid payloads may need updating."
                    )
                )
            else:
                self.stdout.write(self.style.SUCCESS("  Fail batch complete."))
            self.stdout.write("")

        # ── Progress summary ─────────────────────────────────────────────────
        progress = SandboxTestRunner.get_progress(config)
        self.stdout.write(self.style.MIGRATE_HEADING("Certification Progress:"))
        pass_bar = self._progress_bar(progress["pass_count"], REQUIRED_PASS_COUNT)
        fail_bar = self._progress_bar(progress["fail_count"], REQUIRED_FAIL_COUNT)
        self.stdout.write(f"  Pass: {pass_bar} {progress['pass_count']}/{REQUIRED_PASS_COUNT}")
        self.stdout.write(f"  Fail: {fail_bar} {progress['fail_count']}/{REQUIRED_FAIL_COUNT}")
        self.stdout.write("")

        if progress["certification_ready"]:
            self.stdout.write(
                self.style.SUCCESS(
                    "  ✓ Certification complete! Contact DigiTax to request production credentials."
                )
            )
        else:
            remaining_pass = max(0, REQUIRED_PASS_COUNT - progress["pass_count"])
            remaining_fail = max(0, REQUIRED_FAIL_COUNT - progress["fail_count"])
            self.stdout.write(
                f"  Remaining: {remaining_pass} pass tests, {remaining_fail} fail tests."
            )

    def _progress_bar(self, current: int, total: int, width: int = 20) -> str:
        """Render a simple ASCII progress bar."""
        filled = int((min(current, total) / total) * width)
        bar = "█" * filled + "░" * (width - filled)
        return f"[{bar}]"
