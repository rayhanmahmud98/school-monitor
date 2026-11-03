"""Recompute the audit hash chain and report any break (exit code 1 on failure)."""
from django.core.management.base import BaseCommand, CommandError

from finance.services import audit


class Command(BaseCommand):
    help = "Verify the finance audit trail hash chain."

    def handle(self, *args, **options):
        ok, count, message = audit.verify_chain()
        if not ok:
            raise CommandError(message)
        self.stdout.write(self.style.SUCCESS(message))
