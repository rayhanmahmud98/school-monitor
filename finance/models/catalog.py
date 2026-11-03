from django.conf import settings
from django.db import models
from django.db.models import Value
from django.db.models.functions import Coalesce, Lower
from django.utils import timezone


class Frequency(models.TextChoices):
    MONTHLY = "MONTHLY", "Monthly"
    QUARTERLY = "QUARTERLY", "Quarterly"
    TERM = "TERM", "Term-wise"
    ANNUAL = "ANNUAL", "Annual"
    ONE_TIME = "ONE_TIME", "One-time"


class FeeCategory(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"
        ARCHIVED = "ARCHIVED", "Archived"

    code = models.CharField(max_length=20)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    default_frequency = models.CharField(max_length=10, choices=Frequency.choices,
                                         default=Frequency.MONTHLY)
    allow_installments = models.BooleanField(default=False)
    max_installments = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Leave empty for no limit (system maximum is 24).")
    sort_order = models.IntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "fee categories"
        constraints = [
            models.UniqueConstraint(Lower("code"), name="uniq_feecategory_code_ci"),
            models.CheckConstraint(
                condition=models.Q(max_installments__isnull=True) | models.Q(max_installments__gte=1),
                name="feecategory_max_installments_positive"),
        ]

    def save(self, *args, **kwargs):
        self.code = (self.code or "").strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.code})"


class StudentCategory(models.Model):
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "student categories"
        constraints = [models.UniqueConstraint(Lower("code"), name="uniq_studentcategory_code_ci")]

    def save(self, *args, **kwargs):
        self.code = (self.code or "").strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class StudentFeeProfile(models.Model):
    student = models.OneToOneField("students.Student", on_delete=models.PROTECT,
                                   related_name="fee_profile")
    category = models.ForeignKey(StudentCategory, on_delete=models.PROTECT, related_name="profiles")

    def __str__(self):
        return f"{self.student} - {self.category}"


class BillingPeriod(models.Model):
    class Kind(models.TextChoices):
        MONTH = "MONTH", "Month"
        QUARTER = "QUARTER", "Quarter"
        TERM = "TERM", "Term"
        YEAR = "YEAR", "Year"
        ONE_TIME = "ONE_TIME", "One-time"

    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT,
                                      related_name="billing_periods")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    label = models.CharField(max_length=30, help_text="e.g. 2026-03, Q1, Term 1, Admission")
    start_date = models.DateField()
    end_date = models.DateField()
    issue_date = models.DateField(help_text="Invoices may be generated from this date.")
    due_date = models.DateField()

    class Meta:
        ordering = ["start_date", "kind", "label"]
        constraints = [
            models.UniqueConstraint(fields=["academic_year", "kind", "label"],
                                    name="uniq_billingperiod_year_kind_label"),
            models.CheckConstraint(condition=models.Q(end_date__gte=models.F("start_date")),
                                   name="billingperiod_end_after_start"),
            models.CheckConstraint(condition=models.Q(due_date__gte=models.F("issue_date")),
                                   name="billingperiod_due_after_issue"),
        ]

    def __str__(self):
        return f"{self.academic_year} / {self.get_kind_display()} {self.label}"


FREQUENCY_FOR_KIND = {
    "MONTH": "MONTHLY", "QUARTER": "QUARTERLY", "TERM": "TERM",
    "YEAR": "ANNUAL", "ONE_TIME": "ONE_TIME",
}


class FeeRule(models.Model):
    """The amount for a category in a class and year. Edits create new dated versions."""

    fee_category = models.ForeignKey(FeeCategory, on_delete=models.PROTECT, related_name="rules")
    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT,
                                      related_name="fee_rules")
    class_ref = models.ForeignKey("students.Class", null=True, blank=True,
                                  on_delete=models.PROTECT, related_name="fee_rules",
                                  help_text="Empty = all classes.")
    student_category = models.ForeignKey(StudentCategory, null=True, blank=True,
                                         on_delete=models.PROTECT, related_name="fee_rules",
                                         help_text="Empty = all students.")
    frequency = models.CharField(max_length=10, choices=Frequency.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    supersedes = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="superseded_by")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["fee_category__sort_order", "-effective_from"]
        constraints = [
            models.UniqueConstraint(
                "fee_category", "academic_year",
                Coalesce("class_ref", Value(0), output_field=models.IntegerField()),
                Coalesce("student_category", Value(0), output_field=models.IntegerField()),
                "frequency", "effective_from",
                name="uniq_feerule_scope_effective",
            ),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="feerule_amount_positive"),
            models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gte=models.F("effective_from")),
                name="feerule_to_after_from"),
        ]

    def __str__(self):
        scope = self.class_ref or "all classes"
        return f"{self.fee_category.name} / {scope} / {self.amount} from {self.effective_from}"


class InstallmentOption(models.Model):
    class Interval(models.TextChoices):
        MONTHLY = "MONTHLY", "Monthly"
        QUARTERLY = "QUARTERLY", "Quarterly"
        TERM = "TERM", "Termly"
        DAYS = "DAYS", "Every N days"

    class Split(models.TextChoices):
        EQUAL = "EQUAL", "Equal parts"
        CUSTOM = "CUSTOM", "Custom percentages"

    name = models.CharField(max_length=60, help_text="e.g. 3 installments")
    installments = models.PositiveSmallIntegerField(help_text="Number of installments (1 to 24).")
    interval = models.CharField(max_length=10, choices=Interval.choices, default=Interval.MONTHLY)
    interval_days = models.PositiveSmallIntegerField(null=True, blank=True)
    split = models.CharField(max_length=10, choices=Split.choices, default=Split.EQUAL)
    down_payment_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    academic_year = models.ForeignKey("academics.AcademicYear", null=True, blank=True,
                                      on_delete=models.PROTECT, related_name="installment_options",
                                      help_text="Empty = available in every year.")
    categories = models.ManyToManyField(FeeCategory, blank=True, related_name="installment_options",
                                        help_text="Empty = all categories that allow installments.")
    classes = models.ManyToManyField("students.Class", blank=True, related_name="installment_options",
                                     help_text="Empty = all classes.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["installments", "name"]
        constraints = [
            models.CheckConstraint(condition=models.Q(installments__gte=1, installments__lte=24),
                                   name="installmentoption_count_1_24"),
            models.CheckConstraint(
                condition=models.Q(down_payment_percent__gte=0, down_payment_percent__lt=100),
                name="installmentoption_down_payment_range"),
        ]

    def __str__(self):
        return self.name


class InstallmentOptionLine(models.Model):
    option = models.ForeignKey(InstallmentOption, on_delete=models.CASCADE, related_name="lines")
    seq = models.PositiveSmallIntegerField()
    percent = models.DecimalField(max_digits=5, decimal_places=2)

    class Meta:
        ordering = ["option", "seq"]
        constraints = [models.UniqueConstraint(fields=["option", "seq"],
                                               name="uniq_installmentline_option_seq")]

    def __str__(self):
        return f"{self.option} #{self.seq}: {self.percent}%"


class DiscountRule(models.Model):
    class Kind(models.TextChoices):
        SIBLING = "SIBLING", "Sibling discount (automatic)"
        SCHOLARSHIP = "SCHOLARSHIP", "Scholarship"
        STAFF_CHILD = "STAFF_CHILD", "Staff-child waiver"
        WAIVER = "WAIVER", "Waiver"
        MANUAL = "MANUAL", "Other discount"

    class ValueType(models.TextChoices):
        FIXED = "FIXED", "Fixed amount"
        PERCENT = "PERCENT", "Percentage"

    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=15, choices=Kind.choices)
    value_type = models.CharField(max_length=10, choices=ValueType.choices)
    value = models.DecimalField(max_digits=12, decimal_places=2)
    categories = models.ManyToManyField(FeeCategory, blank=True, related_name="discount_rules",
                                        help_text="Empty = applies to every category.")
    priority = models.IntegerField(default=100, help_text="Lower numbers are applied first.")
    stack_group = models.CharField(max_length=30, blank=True,
                                   help_text="Rules in the same group do not stack: the best one wins.")
    max_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                                     help_text="Cap per invoice.")
    annual_cap = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                                     help_text="Cap per student per academic year for this rule.")
    sibling_rank_from = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Sibling rules: applies from this child number (2 = second child).")
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    requires_approval = models.BooleanField(default=False,
                                            help_text="Awards need approval by a second person.")
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["priority", "name"]
        constraints = [models.CheckConstraint(condition=models.Q(value__gt=0),
                                              name="discountrule_value_positive")]

    def __str__(self):
        return self.name


class StudentDiscount(models.Model):
    class Approval(models.TextChoices):
        PENDING = "PENDING", "Pending approval"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    student = models.ForeignKey("students.Student", on_delete=models.PROTECT,
                                related_name="discount_awards")
    rule = models.ForeignKey(DiscountRule, on_delete=models.PROTECT, related_name="awards")
    awarded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.PROTECT, related_name="+")
    approval_status = models.CharField(max_length=10, choices=Approval.choices,
                                       default=Approval.APPROVED)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.PROTECT, related_name="+")
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["student", "approval_status"])]

    def __str__(self):
        return f"{self.student} - {self.rule}"
