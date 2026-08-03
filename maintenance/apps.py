from django.apps import AppConfig


class MaintenanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "maintenance"
    verbose_name = "Maintenance Silo"

    def ready(self):
        import maintenance.signals  # noqa: F401
