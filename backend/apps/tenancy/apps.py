from django.apps import AppConfig


class TenancyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tenancy"
    label = "tenancy"
    verbose_name = "Tenancy"

    def ready(self):
        import apps.tenancy.signals  # noqa: F401 — registers signal handlers
