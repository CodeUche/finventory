from django.apps import AppConfig


class EInvoicingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.einvoicing"
    label = "einvoicing"
    verbose_name = "FIRS E-Invoicing"

    def ready(self):
        import apps.einvoicing.signals  # noqa: F401 — registers post_save handler
