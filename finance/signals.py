import logging

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


def on_post_migrate(sender, **kwargs):
    """After migrations: seed the chart of accounts, sync groups, install DB protections."""
    from django.db import connection

    from . import db_protection
    from .services import groups, ledger

    if "finance_ledgeraccount" not in connection.introspection.table_names():
        return
    ledger.ensure_system_accounts()
    groups.sync_groups()
    db_protection.install()


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def sync_user_group(sender, instance, raw=False, **kwargs):
    """Keep finance-role users in the matching permission group."""
    if raw:
        return
    from .services import groups
    groups.sync_user(instance)


@receiver(post_save, sender="students.Enrollment")
def invoice_on_enrollment(sender, instance, created, raw=False, **kwargs):
    """Generate invoices when a student is enrolled (idempotent; after commit)."""
    if raw or not created or not instance.is_current:
        return
    if not getattr(settings, "FINANCE_AUTO_INVOICE_ON_ENROLLMENT", True):
        return
    enrollment_pk = instance.pk

    def _run():
        from .services import invoicing
        try:
            invoicing.generate_for_enrollment(enrollment_pk)
        except Exception:  # noqa: BLE001 - never break admissions
            logger.exception("Automatic invoice generation failed for enrollment %s", enrollment_pk)

    transaction.on_commit(_run)
