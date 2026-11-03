from django.db import models


class AppendOnlyError(Exception):
    """Raised when code tries to change or delete an append-only financial row."""


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise AppendOnlyError(f"{self.model.__name__} rows are append-only.")

    def delete(self):
        raise AppendOnlyError(f"{self.model.__name__} rows are append-only.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise AppendOnlyError(f"{self.model.__name__} rows are append-only.")


class AppendOnlyModel(models.Model):
    """Rows can be inserted but never updated or deleted (corrections are new rows).

    This is the application layer. PostgreSQL triggers (db_protection.py) enforce
    the same rule underneath.
    """

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AppendOnlyError(f"{type(self).__name__} rows are append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError(f"{type(self).__name__} rows are append-only.")
