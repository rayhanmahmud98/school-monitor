"""Generate invoices for billing periods. Idempotent: safe to run daily from a scheduler.

    python manage.py generate_invoices --current          # every period open for billing today
    python manage.py generate_invoices --period 12        # one specific period
    python manage.py generate_invoices --current --class 3
"""
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from finance.adapters.school import Class
from finance.models import BillingPeriod
from finance.services import invoicing


class Command(BaseCommand):
    help = "Generate invoices for current or specific billing periods (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--current", action="store_true",
                            help="All periods whose issue date has passed and that are still running "
                                 "(plus one-time periods).")
        parser.add_argument("--period", type=int, help="BillingPeriod id.")
        parser.add_argument("--class", dest="class_id", type=int, help="Limit to one class id.")

    def handle(self, *args, **opts):
        today = timezone.localdate()
        if opts["period"]:
            periods = BillingPeriod.objects.filter(pk=opts["period"])
        elif opts["current"]:
            periods = (BillingPeriod.objects.filter(issue_date__lte=today, academic_year__is_current=True)
                       .filter(Q(kind=BillingPeriod.Kind.ONE_TIME) | Q(end_date__gte=today)))
        else:
            raise CommandError("Use --current or --period <id>.")
        class_ref = Class.objects.filter(pk=opts["class_id"]).first() if opts["class_id"] else None
        if opts["class_id"] and class_ref is None:
            raise CommandError("No such class.")
        if not periods.exists():
            self.stdout.write("No matching billing periods.")
            return
        for period in periods.select_related("academic_year"):
            try:
                result = invoicing.generate_bulk(period, actor=None, class_ref=class_ref)
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(self.style.ERROR(f"{period}: {exc}"))
                continue
            self.stdout.write(f"{period}: {len(result.created)} created, {result.skipped} skipped, "
                              f"{len(result.failed)} failed")
