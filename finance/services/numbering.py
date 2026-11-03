"""Gapless document numbers, allocated under a row lock inside the caller's transaction."""
from django.db import transaction
from django.utils import timezone

from ..models import NumberSequence

PREFIXES = {
    "invoice": "INV", "receipt": "RC", "expense": "EXP",
    "transfer": "TRF", "refund": "RFD", "batch": "BAT",
}


def next_number(key, on_date=None):
    """Return e.g. INV-2026-000001. Call inside the transaction that uses the number
    so a rollback also rolls back the counter (no gaps)."""
    year = (on_date or timezone.localdate()).year
    with transaction.atomic():
        seq, _ = NumberSequence.objects.select_for_update().get_or_create(key=key, year=year)
        value = seq.next_value
        seq.next_value = value + 1
        seq.save(update_fields=["next_value"])
    return f"{PREFIXES[key]}-{year}-{value:06d}"
