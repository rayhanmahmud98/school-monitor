"""Demo finance setup on top of seed_data: categories, fees, periods, options, discounts.

    python manage.py seed_finance                 # configuration only
    python manage.py seed_finance --invoices      # also issue this month's invoices

Safe to repeat.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from academics.models import AcademicYear
from accounts.models import User
from finance.adapters.school import Class
from finance.models import (BillingPeriod, DiscountRule, FeeCategory, InstallmentOption,
                            StudentCategory)
from finance.services import fees, invoicing
from finance.services.periods import create_monthly_periods

CATEGORIES = [
    # code, name, frequency, installments allowed, base amount, step per class
    ("TUITION", "Tuition fee", "MONTHLY", True, 1500, 250),
    ("TRANSPORT", "Transport fee", "MONTHLY", False, 800, 0),
    ("ADMISSION", "Admission fee", "ONE_TIME", False, 5000, 0),
    ("EXAM", "Examination fee", "ANNUAL", True, 1200, 100),
    ("LAB", "Laboratory fee", "ANNUAL", False, 600, 50),
]


class Command(BaseCommand):
    help = "Create demo fee categories, amounts, billing periods, installment options and discounts."

    def add_arguments(self, parser):
        parser.add_argument("--invoices", action="store_true",
                            help="Also generate invoices for periods open today.")

    def handle(self, *args, **opts):
        actor = User.objects.filter(username="admin").first() or User.objects.filter(role="ADMIN").first()
        year = AcademicYear.objects.filter(is_current=True).first()
        if not year:
            raise CommandError("No current academic year. Run seed_data first.")
        today = timezone.localdate()

        if not (year.start_date and year.end_date):
            first_year = int(year.name[:4]) if year.name[:4].isdigit() else today.year
            year.start_date, year.end_date = date(first_year, 1, 1), date(first_year, 12, 31)
            year.save()
            self.stdout.write(f"Set {year} dates to {year.start_date} - {year.end_date} (calendar year).")

        StudentCategory.objects.get_or_create(code="REGULAR", defaults={"name": "Regular"})

        cats = {}
        for order, (code, name, freq, inst, _base, _step) in enumerate(CATEGORIES):
            cats[code], _ = FeeCategory.objects.get_or_create(
                code=code, defaults={"name": name, "default_frequency": freq, "sort_order": order,
                                     "allow_installments": inst, "max_installments": 12 if inst else None,
                                     "created_by": actor})

        months = create_monthly_periods(year, issue_day=1, due_day=10)
        BillingPeriod.objects.get_or_create(
            academic_year=year, kind="ONE_TIME", label="Admission",
            defaults={"start_date": year.start_date, "end_date": year.end_date,
                      "issue_date": year.start_date, "due_date": year.start_date + timedelta(days=30)})
        BillingPeriod.objects.get_or_create(
            academic_year=year, kind="YEAR", label="Annual",
            defaults={"start_date": year.start_date, "end_date": year.end_date,
                      "issue_date": year.start_date, "due_date": year.start_date + timedelta(days=60)})

        classes = list(Class.objects.filter(academic_year=year.name).order_by("name", "section"))
        for index, cls in enumerate(classes):
            for code, _n, _f, _i, base, step in CATEGORIES:
                fees.set_amount(cats[code], year, cls, Decimal(base + step * index),
                                year.start_date, actor)

        for n in (1, 2, 3, 4, 6):
            InstallmentOption.objects.get_or_create(
                name="Pay in full" if n == 1 else f"{n} installments",
                defaults={"installments": n, "interval": "MONTHLY", "split": "EQUAL"})

        DiscountRule.objects.get_or_create(
            name="Sibling discount (2nd child onward)",
            defaults={"kind": "SIBLING", "value_type": "PERCENT", "value": Decimal("10"),
                      "sibling_rank_from": 2, "priority": 10, "stack_group": "family",
                      "effective_from": year.start_date, "created_by": actor})
        DiscountRule.objects.get_or_create(
            name="Merit scholarship 25%",
            defaults={"kind": "SCHOLARSHIP", "value_type": "PERCENT", "value": Decimal("25"),
                      "priority": 20, "requires_approval": True,
                      "effective_from": year.start_date, "created_by": actor})

        self.stdout.write(self.style.SUCCESS(
            f"Finance demo configured: {len(classes)} classes, {months} new monthly periods."))

        if opts["invoices"]:
            from django.db.models import Q
            periods = (BillingPeriod.objects.filter(academic_year=year, issue_date__lte=today)
                       .filter(Q(kind="ONE_TIME") | Q(end_date__gte=today)))
            for period in periods:
                result = invoicing.generate_bulk(period, actor)
                self.stdout.write(f"{period}: {len(result.created)} created, {result.skipped} skipped")
