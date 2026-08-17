"""
One-time setup command: registers Audity's Telegram webhook endpoint with
Telegram's Bot API (setWebhook).

MUST be run manually, exactly once per environment, AFTER this backend
revision (which adds apps.connectors.views.telegram_webhook /
/api/v1/connectors/webhook/telegram/) is deployed and reachable at a public
HTTPS URL. Running it before deployment would point the live, single,
shared @AudityNotifyBot's webhook at a URL that doesn't exist yet, breaking
Telegram delivery for every org until re-run correctly — this is exactly
the kind of state-changing, production-affecting action the operating
rules require flagging rather than running automatically.

Usage:
    python manage.py setup_telegram_webhook https://audity-backend-production-30f9.up.railway.app/api/v1/connectors/webhook/telegram/ \\
        [--secret <TELEGRAM_WEBHOOK_SECRET value, if you set one>]

Verify afterwards with Telegram's own getWebhookInfo (no write, safe to run
anytime):
    python manage.py shell -c "from apps.connectors import telegram; import json; print(telegram._call('getWebhookInfo', {}).json())"
"""

from django.core.management.base import BaseCommand, CommandError

from apps.connectors import telegram


class Command(BaseCommand):
    help = "One-time: register Audity's Telegram webhook URL with Telegram's Bot API. Do not run before the endpoint is deployed."

    def add_arguments(self, parser):
        parser.add_argument("url", type=str, help="Public HTTPS URL of the deployed /connectors/webhook/telegram/ endpoint.")
        parser.add_argument(
            "--secret", type=str, default=None,
            help="Value of TELEGRAM_WEBHOOK_SECRET, if configured. Must match the backend's env var exactly.",
        )

    def handle(self, *args, **options):
        url = options["url"]
        secret = options.get("secret")

        if not url.startswith("https://"):
            raise CommandError("Telegram requires an https:// webhook URL.")

        self.stdout.write(f"Registering Telegram webhook -> {url}")
        try:
            resp = telegram.set_webhook(url=url, secret_token=secret)
        except telegram.TelegramNotConfiguredError as exc:
            raise CommandError(str(exc))
        except telegram.TelegramAPIError as exc:
            raise CommandError(f"Could not reach Telegram: {exc}")

        body = resp.json() if resp.content else {}
        if not body.get("ok"):
            raise CommandError(f"Telegram rejected setWebhook: {body}")

        self.stdout.write(self.style.SUCCESS(f"Telegram webhook registered: {body.get('description', 'ok')}"))
