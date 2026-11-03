from django.db import models

from ..constants import PERMISSIONS


class FinanceRights(models.Model):
    """Holds the custom finance permissions (no table is created for it)."""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = PERMISSIONS
