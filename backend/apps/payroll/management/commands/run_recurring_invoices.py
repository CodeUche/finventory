from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Generate recurring invoices that are due today'

    def handle(self, *args, **options):
        from apps.sales.models import RecurringInvoice
        from django.utils import timezone
        today = timezone.now().date()
        due = RecurringInvoice.objects.filter(is_active=True, next_run_date__lte=today)
        self.stdout.write(f"Found {due.count()} recurring invoices due")
        # TODO: generate invoices for each
