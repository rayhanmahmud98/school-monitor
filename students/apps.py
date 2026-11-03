from django.apps import AppConfig


class StudentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "students"

    def ready(self):
        # Importing the module registers its @receiver hooks. Do not remove.
        from . import signals  # noqa: F401
