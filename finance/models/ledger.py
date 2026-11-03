import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from .base import AppendOnlyModel


class LedgerAccount(models.Model):
    class Kind(models.TextChoices):
        ASSET = "ASSET", "Asset"
        LIABILITY = "LIABILITY", "Liability"
        INCOME = "INCOME", "Income"
        EXPENSE = "EXPENSE", "Expense"
        EQUITY = "EQUITY", "Equity"

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    system_key = models.CharField(max_length=40, unique=True, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.name}"


class LedgerTransaction(AppendOnlyModel):
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    tx_type = models.CharField(max_length=40, db_index=True)
    posting_date = models.DateField(db_index=True)
    period = models.ForeignKey("finance.FinancePeriod", on_delete=models.PROTECT,
                               related_name="transactions")
    description = models.CharField(max_length=255, blank=True)
    source_type = models.CharField(max_length=40, blank=True)
    source_id = models.PositiveBigIntegerField(null=True, blank=True)
    reverses = models.OneToOneField("self", null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="reversed_by")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-posting_date", "-id"]
        indexes = [models.Index(fields=["source_type", "source_id"])]

    def __str__(self):
        return f"{self.tx_type} {self.posting_date} #{self.pk}"


class LedgerLine(AppendOnlyModel):
    tx = models.ForeignKey(LedgerTransaction, on_delete=models.PROTECT, related_name="lines")
    account = models.ForeignKey(LedgerAccount, on_delete=models.PROTECT, related_name="lines")
    debit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    student = models.ForeignKey("students.Student", null=True, blank=True,
                                on_delete=models.PROTECT, related_name="+")
    fee_category = models.ForeignKey("finance.FeeCategory", null=True, blank=True,
                                     on_delete=models.PROTECT, related_name="ledger_lines")

    class Meta:
        indexes = [models.Index(fields=["account", "tx"])]
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(debit__gt=0, credit=0) | models.Q(credit__gt=0, debit=0)),
                name="ledgerline_exactly_one_side",
            ),
        ]

    def __str__(self):
        return f"{self.account.code} Dr {self.debit} Cr {self.credit}"
