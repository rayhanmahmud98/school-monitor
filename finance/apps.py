from django.apps import AppConfig
from django.db.models.signals import post_migrate


class FinanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "finance"

    def ready(self):
        from . import signals  # noqa: F401  (registers @receiver hooks)
        post_migrate.connect(signals.on_post_migrate, sender=self,
                             dispatch_uid="finance_post_migrate")
