import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from .base import AppendOnlyModel


class StudentInvoice(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ISSUED = "ISSUED", "Issued"
        PARTIAL = "PARTIAL", "Partly paid"
        PAID = "PAID", "Paid"
        CANCELLED = "CANCELLED", "Cancelled"

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    invoice_no = models.CharField(max_length=30, unique=True)
    student = models.ForeignKey("students.Student", on_delete=models.PROTECT, related_name="invoices")
    enrollment = models.ForeignKey("students.Enrollment", null=True, blank=True,
                                   on_delete=models.PROTECT, related_name="invoices")
    fee_category = models.ForeignKey("finance.FeeCategory", on_delete=models.PROTECT,
                                     related_name="invoices")
    fee_rule = models.ForeignKey("finance.FeeRule", null=True, blank=True,
                                 on_delete=models.PROTECT, related_name="invoices")
    billing_period = models.ForeignKey("finance.BillingPeriod", on_delete=models.PROTECT,
                                       related_name="invoices")
    # Snapshots: renaming or deactivating a category never rewrites history.
    description_snapshot = models.CharField(max_length=200)
    category_code_snapshot = models.CharField(max_length=20)
    category_name_snapshot = models.CharField(max_length=100)

    original_amount = models.DecimalField(max_digits=14, decimal_places=2)
    discount_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    penalty_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    net_payable = models.DecimalField(max_digits=14, decimal_places=2)
    paid_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    balance = models.DecimalField(max_digits=14, decimal_places=2)

    issue_date = models.DateField()
    due_date = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ISSUED)
    cancelled_reason = models.TextField(blank=True)
    issue_tx = models.ForeignKey("finance.LedgerTransaction", null=True, blank=True,
                                 on_delete=models.PROTECT, related_name="+")
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                  on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-issue_date", "-id"]
        indexes = [
            models.Index(fields=["student", "status"]),
            models.Index(fields=["due_date", "status"]),
            models.Index(fields=["billing_period", "fee_category"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "fee_rule", "billing_period"],
                condition=Q(fee_rule__isnull=False) & ~Q(status="CANCELLED"),
                name="uniq_invoice_student_rule_period_live",
            ),
            models.CheckConstraint(
                condition=Q(original_amount__gte=0, discount_total__gte=0,
                            penalty_total__gte=0, paid_total__gte=0),
                name="invoice_amounts_non_negative"),
            models.CheckConstraint(
                condition=Q(net_payable=F("original_amount") - F("discount_total") + F("penalty_total")),
                name="invoice_net_matches_parts"),
            models.CheckConstraint(
                condition=Q(balance=F("net_payable") - F("paid_total")),
                name="invoice_balance_matches"),
            models.CheckConstraint(condition=Q(balance__gte=0), name="invoice_balance_non_negative"),
        ]

    @property
    def is_overdue(self):
        return (self.status in (self.Status.ISSUED, self.Status.PARTIAL)
                and self.balance > 0 and self.due_date < timezone.localdate())

    def __str__(self):
        return f"{self.invoice_no} - {self.student.full_name}"


class InvoiceAdjustment(AppendOnlyModel):
    class Kind(models.TextChoices):
        DISCOUNT = "DISCOUNT", "Discount"
        WAIVER = "WAIVER", "Waiver"
        PENALTY = "PENALTY", "Penalty"
        CORRECTION = "CORRECTION", "Correction"

    invoice = models.ForeignKey(StudentInvoice, on_delete=models.PROTECT, related_name="adjustments")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2,
                                 help_text="Signed: negative reduces what is payable.")
    discount_rule = models.ForeignKey("finance.DiscountRule", null=True, blank=True,
                                      on_delete=models.PROTECT, related_name="adjustments")
    student_discount = models.ForeignKey("finance.StudentDiscount", null=True, blank=True,
                                         on_delete=models.PROTECT, related_name="adjustments")
    reason = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.PROTECT, related_name="+")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.PROTECT, related_name="+")
    ledger_tx = models.ForeignKey("finance.LedgerTransaction", null=True, blank=True,
                                  on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["id"]
        constraints = [models.CheckConstraint(condition=~Q(amount=0), name="invoiceadjustment_nonzero")]

    def __str__(self):
        return f"{self.invoice.invoice_no} {self.kind} {self.amount}"
