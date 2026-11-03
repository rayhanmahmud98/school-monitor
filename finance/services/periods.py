import calendar
from datetime import timedelta

from ..models import BillingPeriod, FinancePeriod


class PeriodClosed(Exception):
    """Posting date falls in a closed finance period."""


def month_bounds(day):
    first = day.replace(day=1)
    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    return first, last


def get_open_period(day):
    """Return the monthly period containing `day`, creating it on first use.
    Raises PeriodClosed if it has been closed."""
    first, last = month_bounds(day)
    period, _ = FinancePeriod.objects.get_or_create(
        label=day.strftime("%Y-%m"), defaults={"start_date": first, "end_date": last})
    if period.status != FinancePeriod.Status.OPEN:
        raise PeriodClosed(f"Finance period {period.label} is closed; nothing can be posted to it.")
    return period


def create_monthly_periods(year, issue_day=1, due_day=10):
    """Create one MONTH billing period per month of the academic year. Idempotent.
    Returns the number of periods created."""
    created = 0
    cursor = year.start_date.replace(day=1)
    while cursor <= year.end_date:
        first, last = month_bounds(cursor)
        _, made = BillingPeriod.objects.get_or_create(
            academic_year=year, kind=BillingPeriod.Kind.MONTH, label=cursor.strftime("%Y-%m"),
            defaults={"start_date": first, "end_date": last,
                      "issue_date": first.replace(day=issue_day),
                      "due_date": first.replace(day=due_day)})
        created += 1 if made else 0
        cursor = last + timedelta(days=1)
    return created
