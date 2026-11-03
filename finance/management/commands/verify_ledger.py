"""Cross-check cached totals against the ledger. Exit code 1 on any mismatch."""
from django.core.management.base import BaseCommand, CommandError
from django.db.models import F, Sum

from finance.models import LedgerLine, LedgerTransaction, StudentInvoice
from finance.money import ZERO, money
from finance.services import ledger


class Command(BaseCommand):
    help = "Verify ledger balance and that invoice balances agree with the receivables account."

    def handle(self, *args, **options):
        problems = []

        agg = LedgerLine.objects.aggregate(d=Sum("debit"), c=Sum("credit"))
        if money(agg["d"]) != money(agg["c"]):
            problems.append(f"Total debits {money(agg['d'])} differ from total credits {money(agg['c'])}.")

        for tx in LedgerTransaction.objects.iterator():
            totals = tx.lines.aggregate(d=Sum("debit"), c=Sum("credit"))
            if money(totals["d"]) != money(totals["c"]):
                problems.append(f"Transaction #{tx.pk} is unbalanced.")

        bad = StudentInvoice.objects.exclude(balance=F("net_payable") - F("paid_total")).count()
        if bad:
            problems.append(f"{bad} invoice(s) have a balance that does not equal net minus paid.")

        owed = StudentInvoice.objects.exclude(status=StudentInvoice.Status.CANCELLED) \
            .aggregate(t=Sum("balance"))["t"] or ZERO
        receivable = ledger.account_balance(ledger.account("RECEIVABLE"))
        if money(owed) != receivable:
            problems.append(f"Invoice balances total {money(owed)} but the receivables account shows "
                            f"{receivable}.")

        if problems:
            for line in problems:
                self.stderr.write(self.style.ERROR(line))
            raise CommandError(f"{len(problems)} problem(s) found.")
        self.stdout.write(self.style.SUCCESS("Ledger and invoice totals agree."))
