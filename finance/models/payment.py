"""Payment receipts. Clerk enters; accountant approves; receipt PDF is issued."""
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from .base import AppendOnlyModel  # noqa: F401 (kept for import compatibility)


class PaymentReceipt(models.Model):
    """One payment received from a student. May or may not be applied to an invoice yet."""

    class Method(models.TextChoices):
        CASH = "CASH", "Cash"
        BANK_TRANSFER = "BANK", "Bank transfer"
        CHEQUE = "CHEQUE", "Cheque"
        CARD = "CARD", "Card"
        BKASH = "BKASH", "bKash"
        NAGAD = "NAGAD", "Nagad"
        ROCKET = "ROCKET", "Rocket"
        OTHER = "OTHER", "Other"

    class Status(models.TextChoices):
        # Legacy (existing rows only):
        PENDING = "PENDING", "Pending approval"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        # New (this workflow):
        ACTIVE = "ACTIVE", "Active"
        CANCELLED = "CANCELLED", "Cancelled"   # reserved, not produced this phase
        REFUNDED = "REFUNDED", "Refunded"      # reserved, not produced this phase

    class ReferenceType(models.TextChoices):
        NONE = "NONE", "None"
        TXN_ID = "TXN_ID", "Transaction ID"
        CHEQUE_NO = "CHEQUE_NO", "Cheque number"
        REF_NO = "REF_NO", "Reference number"

    number = models.CharField(max_length=30, unique=True, blank=True)

    invoice = models.ForeignKey(
        "finance.StudentInvoice",
        on_delete=models.PROTECT,
        related_name="payments",
        null=True, blank=True,
    )

    student = models.ForeignKey(
        "students.Student",
        on_delete=models.PROTECT,
        related_name="payment_receipts",
        null=True, blank=True,
    )

    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=10, choices=Method.choices, default=Method.CASH)
    reference = models.CharField(
        max_length=100, blank=True,
        help_text="Bank slip number, cheque number, transaction ID…",
    )
    reference_type = models.CharField(
        max_length=10, choices=ReferenceType.choices, default=ReferenceType.NONE,
    )
    cheque_date = models.DateField(null=True, blank=True)
    bank_name = models.CharField(max_length=100, blank=True)
    branch_name = models.CharField(max_length=100, blank=True)
    note = models.TextField(blank=True)

    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="payments_received",
    )
    received_at = models.DateTimeField(default=timezone.now)
    payment_date = models.DateField(null=True, blank=True)

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="payments_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    ledger_transaction = models.ForeignKey(
        "finance.LedgerTransaction", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="payment_receipts",
    )

    idempotency_key = models.CharField(max_length=64, unique=True, null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-received_at"]
        indexes = [
            models.Index(fields=["invoice", "status"]),
            models.Index(fields=["status", "-received_at"]),
            models.Index(fields=["student", "status"]),
        ]

    def __str__(self):
        student = self.student.full_name if self.student_id else "?"
        return f"{self.number} — {student} ({self.amount})"

    @property
    def is_approved(self):
        return self.status == self.Status.APPROVED

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE

    def save(self, *args, **kwargs):
        if not self.number:
            year = timezone.localdate().year
            last = (
                PaymentReceipt.objects
                .filter(number__startswith=f"RCPT-{year}-")
                .order_by("-number")
                .first()
            )
            n = 1
            if last:
                try:
                    n = int(last.number.rsplit("-", 1)[1]) + 1
                except (ValueError, IndexError):
                    pass
            self.number = f"RCPT-{year}-{n:06d}"
        super().save(*args, **kwargs)


class PaymentAllocation(models.Model):
    """Links one payment to one invoice. A payment may be split across invoices."""

    payment = models.ForeignKey(
        "finance.PaymentReceipt",
        on_delete=models.PROTECT,
        related_name="allocations",
    )
    invoice = models.ForeignKey(
        "finance.StudentInvoice",
        on_delete=models.PROTECT,
        related_name="allocations",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    allocated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="allocations_made",
    )
    allocated_at = models.DateTimeField(default=timezone.now)

    idempotency_key = models.CharField(max_length=64, unique=True, null=True, blank=True)

    class Meta:
        ordering = ["-allocated_at"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(amount__gt=0),
                name="paymentallocation_amount_positive",
            ),
        ]

    def __str__(self):
        return f"Alloc {self.payment.number} → {self.invoice.invoice_no} ({self.amount})"