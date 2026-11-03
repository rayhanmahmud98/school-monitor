"""The only code that writes ledger rows."""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from ..constants import SYSTEM_ACCOUNTS
from ..models import LedgerAccount, LedgerLine, LedgerTransaction
from ..money import ZERO, money
from .periods import get_open_period


class LedgerError(Exception):
    pass


def ensure_system_accounts():
    for key, (code, name, kind) in SYSTEM_ACCOUNTS.items():
        LedgerAccount.objects.get_or_create(
            system_key=key, defaults={"code": code, "name": name, "kind": kind})


def account(key):
    try:
        return LedgerAccount.objects.get(system_key=key)
    except LedgerAccount.DoesNotExist:
        ensure_system_accounts()
        return LedgerAccount.objects.get(system_key=key)


@transaction.atomic
def post(*, tx_type, posting_date, description, lines, actor=None, source=None, reverses=None):
    """Post a balanced transaction.

    lines: dicts with `account` (system key or LedgerAccount) and either `debit` or
    `credit`, optionally `student` and `fee_category`. Zero lines are skipped.
    source: (source_type, source_id) of the record that caused the posting.
    """
    period = get_open_period(posting_date)
    prepared, total_debit, total_credit = [], ZERO, ZERO
    for line in lines:
        debit, credit = money(line.get("debit", 0)), money(line.get("credit", 0))
        if debit < 0 or credit < 0:
            raise LedgerError("Ledger amounts cannot be negative.")
        if debit == 0 and credit == 0:
            continue
        if debit > 0 and credit > 0:
            raise LedgerError("A ledger line is either a debit or a credit, not both.")
        acct = line["account"]
        if not isinstance(acct, LedgerAccount):
            acct = account(acct)
        prepared.append((acct, debit, credit, line.get("student"), line.get("fee_category")))
        total_debit += debit
        total_credit += credit
    if not prepared or total_debit != total_credit:
        raise LedgerError(f"Unbalanced transaction: debit {total_debit} vs credit {total_credit}.")

    tx = LedgerTransaction.objects.create(
        tx_type=tx_type, posting_date=posting_date, period=period, description=description[:255],
        source_type=(source[0] if source else ""), source_id=(source[1] if source else None),
        reverses=reverses, created_by=actor if getattr(actor, "is_authenticated", False) else None,
        created_at=timezone.now())
    LedgerLine.objects.bulk_create([
        LedgerLine(tx=tx, account=a, debit=d, credit=c, student=s, fee_category=f)
        for a, d, c, s, f in prepared])
    return tx


def reverse(tx, *, actor, reason, posting_date=None):
    """Post the mirror image of `tx` (debits and credits swapped), dated today by default."""
    mirrored = [
        {"account": ln.account, "debit": ln.credit, "credit": ln.debit,
         "student": ln.student, "fee_category": ln.fee_category}
        for ln in tx.lines.select_related("account", "student", "fee_category")
    ]
    return post(tx_type=f"{tx.tx_type}_reversal", posting_date=posting_date or timezone.localdate(),
                description=f"Reversal of #{tx.pk}: {reason}"[:255], lines=mirrored, actor=actor,
                source=(tx.source_type, tx.source_id), reverses=tx)


def account_balance(acct):
    """Net debit-minus-credit for an account (positive = net debit)."""
    from django.db.models import Sum
    agg = LedgerLine.objects.filter(account=acct).aggregate(d=Sum("debit"), c=Sum("credit"))
    return money((agg["d"] or Decimal("0")) - (agg["c"] or Decimal("0")))
