from decimal import Decimal, InvalidOperation

from django import forms
from django.utils import timezone
import uuid

from academics.models import AcademicYear
from accounts.forms import TailwindFormMixin
from students.models import Class, Student

from .models import (
    BillingPeriod, DiscountRule, FeeCategory, FeeRule, InstallmentOption,
    InstallmentOptionLine, PaymentReceipt, StudentCategory, StudentDiscount,
)
from .services.invoicing import ADJUSTMENT_CHOICES


class FinanceFormMixin(TailwindFormMixin):
    """Tailwind styling plus native date pickers."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field, forms.DateField):
                css = field.widget.attrs.get("class", "")
                field.widget = forms.DateInput(
                    attrs={"type": "date", "class": css}, format="%Y-%m-%d"
                )


class FeeCategoryForm(FinanceFormMixin, forms.ModelForm):
    class Meta:
        model = FeeCategory
        fields = [
            "code", "name", "description", "default_frequency",
            "allow_installments", "max_installments", "sort_order", "status",
        ]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        clash = FeeCategory.objects.filter(code__iexact=code).exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError("Another category already uses this code.")
        return code

    def clean_max_installments(self):
        value = self.cleaned_data.get("max_installments")
        if value is not None and not 1 <= value <= 24:
            raise forms.ValidationError("Use a number from 1 to 24.")
        return value


class StudentCategoryForm(FinanceFormMixin, forms.ModelForm):
    class Meta:
        model = StudentCategory
        fields = ["code", "name", "is_active"]


class BillingPeriodForm(FinanceFormMixin, forms.ModelForm):
    class Meta:
        model = BillingPeriod
        fields = ["academic_year", "kind", "label", "start_date", "end_date",
                  "issue_date", "due_date"]

    def clean(self):
        cleaned = super().clean()
        s, e, i, d = (cleaned.get(k) for k in
                      ("start_date", "end_date", "issue_date", "due_date"))
        if s and e and e < s:
            self.add_error("end_date", "End date cannot be before the start date.")
        if i and d and d < i:
            self.add_error("due_date", "Due date cannot be before the issue date.")
        return cleaned


class MonthlyPeriodsForm(FinanceFormMixin, forms.Form):
    academic_year = forms.ModelChoiceField(AcademicYear.objects.all())
    issue_day = forms.IntegerField(
        min_value=1, max_value=28, initial=1,
        help_text="Day of the month invoices may be generated from.",
    )
    due_day = forms.IntegerField(
        min_value=1, max_value=28, initial=10,
        help_text="Day of the month payment is due.",
    )

    def clean_academic_year(self):
        year = self.cleaned_data["academic_year"]
        if not (year.start_date and year.end_date):
            raise forms.ValidationError(
                "This academic year has no start and end dates. "
                "Add them under Academic years first."
            )
        return year

    def clean(self):
        cleaned = super().clean()
        if (cleaned.get("issue_day") and cleaned.get("due_day")
                and cleaned["due_day"] < cleaned["issue_day"]):
            self.add_error("due_day", "The due day cannot be earlier than the issue day.")
        return cleaned


class InstallmentOptionForm(FinanceFormMixin, forms.ModelForm):
    custom_percents = forms.CharField(
        required=False, label="Custom percentages",
        help_text="Only for custom split. Comma separated, e.g. 50,30,20.",
    )

    class Meta:
        model = InstallmentOption
        fields = ["name", "installments", "interval", "interval_days", "split",
                  "down_payment_percent", "academic_year", "categories",
                  "classes", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["custom_percents"].initial = ",".join(
                f"{ln.percent:g}" for ln in self.instance.lines.all()
            )

    def clean(self):
        cleaned = super().clean()
        n = cleaned.get("installments")
        if n is not None and not 1 <= n <= 24:
            self.add_error("installments", "Use a number from 1 to 24.")
        if (cleaned.get("interval") == InstallmentOption.Interval.DAYS
                and not cleaned.get("interval_days")):
            self.add_error("interval_days",
                           "Enter the number of days between installments.")
        for category in cleaned.get("categories") or []:
            if not category.allow_installments:
                self.add_error("categories",
                               f"{category.name} does not allow installments.")
            elif category.max_installments and n and n > category.max_installments:
                self.add_error("categories",
                               f"{category.name} allows at most {category.max_installments} installments.")
        self._percents = []
        if cleaned.get("split") == InstallmentOption.Split.CUSTOM:
            raw = [p.strip() for p in (cleaned.get("custom_percents") or "").split(",") if p.strip()]
            try:
                self._percents = [Decimal(p) for p in raw]
            except InvalidOperation:
                self.add_error("custom_percents", "Use numbers separated by commas.")
                return cleaned
            if n and len(self._percents) != n:
                self.add_error("custom_percents", f"Enter exactly {n} percentages.")
            elif sum(self._percents, Decimal("0")) != Decimal("100"):
                self.add_error("custom_percents", "The percentages must total 100.")
            elif any(p <= 0 for p in self._percents):
                self.add_error("custom_percents",
                               "Every percentage must be greater than zero.")
        return cleaned

    def save(self, commit=True):
        option = super().save(commit=commit)
        if commit:
            option.lines.all().delete()
            if option.split == InstallmentOption.Split.CUSTOM:
                InstallmentOptionLine.objects.bulk_create([
                    InstallmentOptionLine(option=option, seq=i, percent=p)
                    for i, p in enumerate(self._percents, start=1)
                ])
        return option


class DiscountRuleForm(FinanceFormMixin, forms.ModelForm):
    class Meta:
        model = DiscountRule
        fields = ["name", "kind", "value_type", "value", "categories", "priority",
                  "stack_group", "max_amount", "annual_cap", "sibling_rank_from",
                  "effective_from", "effective_to", "requires_approval", "is_active"]

    def clean(self):
        cleaned = super().clean()
        if (cleaned.get("value_type") == DiscountRule.ValueType.PERCENT
                and cleaned.get("value") is not None):
            if not 0 < cleaned["value"] <= 100:
                self.add_error("value", "A percentage must be between 0 and 100.")
        if (cleaned.get("kind") == DiscountRule.Kind.SIBLING
                and not cleaned.get("sibling_rank_from")):
            self.add_error("sibling_rank_from",
                           "Sibling rules need the child number they start from.")
        e, s = cleaned.get("effective_to"), cleaned.get("effective_from")
        if e and s and e < s:
            self.add_error("effective_to",
                           "End date cannot be before the start date.")
        return cleaned


class _StudentChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.full_name} - {obj.student_id} - {obj.class_ref}"


class StudentDiscountForm(FinanceFormMixin, forms.ModelForm):
    student = _StudentChoice(
        Student.objects.filter(is_active=True).select_related("class_ref")
    )
    rule = forms.ModelChoiceField(
        DiscountRule.objects.filter(is_active=True).exclude(
            kind=DiscountRule.Kind.SIBLING
        )
    )

    class Meta:
        model = StudentDiscount
        fields = ["student", "rule", "valid_from", "valid_to", "reason"]
        widgets = {"reason": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean(self):
        cleaned = super().clean()
        s, e = cleaned.get("valid_from"), cleaned.get("valid_to")
        if s and e and e < s:
            self.add_error("valid_to", "End date cannot be before the start date.")
        return cleaned

    def save(self, commit=True):
        award = super().save(commit=False)
        award.awarded_by = self.user
        award.approval_status = (
            StudentDiscount.Approval.PENDING
            if award.rule.requires_approval
            else StudentDiscount.Approval.APPROVED
        )
        if commit:
            award.save()
        return award


class BulkGenerateForm(FinanceFormMixin, forms.Form):
    period = forms.ModelChoiceField(
        BillingPeriod.objects.select_related("academic_year")
    )
    class_ref = forms.ModelChoiceField(
        Class.objects.all(), required=False, label="Class (optional)",
        empty_label="All classes",
    )

    def clean(self):
        cleaned = super().clean()
        period, cls = cleaned.get("period"), cleaned.get("class_ref")
        if period and cls and cls.academic_year != period.academic_year.name:
            self.add_error("class_ref", "This class belongs to a different academic year.")
        return cleaned


class AdjustmentForm(FinanceFormMixin, forms.Form):
    choice = forms.ChoiceField(
        choices=[(k, v[2]) for k, v in ADJUSTMENT_CHOICES.items()],
        label="Adjustment type",
    )
    amount = forms.DecimalField(min_value=Decimal("0.01"),
                                max_digits=14, decimal_places=2)
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}))


class CancelForm(FinanceFormMixin, forms.Form):
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}))


class PaymentReceiptForm(FinanceFormMixin, forms.ModelForm):
    """Form for recording a payment against an existing invoice (legacy path)."""

    class Meta:
        model = PaymentReceipt
        fields = ("amount", "method", "reference", "note")
        widgets = {
            "reference": forms.TextInput(
                attrs={"placeholder": "Bank slip / cheque number"}),
            "note": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, invoice=None, **kwargs):
        self.invoice = invoice
        super().__init__(*args, **kwargs)
        if invoice:
            self.fields["amount"].widget.attrs["max"] = str(invoice.balance)
            self.fields["amount"].widget.attrs["placeholder"] = (
                f"Up to {invoice.balance}"
            )

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise forms.ValidationError("Amount must be positive.")
        if self.invoice and amount > self.invoice.balance:
            raise forms.ValidationError(
                f"Amount cannot exceed outstanding balance {self.invoice.balance}."
            )
        return amount


class ClerkNewInvoiceForm(FinanceFormMixin, forms.Form):
    """
    Unified screen: either create invoices for the selected categories and
    receive a payment now (mode=invoice), or receive a payment without
    creating an invoice and hold it as student credit (mode=credit).
    """

    MODE_INVOICE = "invoice"
    MODE_CREDIT = "credit"

    mode = forms.CharField(
        widget=forms.HiddenInput(),
        initial=MODE_INVOICE,
    )

    student = forms.ModelChoiceField(
        queryset=None,
        label="Student",
        widget=forms.Select(attrs={"class": "input"}),
    )
    billing_period = forms.ModelChoiceField(
        queryset=None,
        label="Billing period",
        required=False,
        help_text="Required only when creating an invoice.",
        widget=forms.Select(attrs={"class": "input"}),
    )
    categories = forms.ModelMultipleChoiceField(
        queryset=None,
        label="Categories to bill",
        required=False,
        help_text="Leave empty to receive a payment without creating an invoice.",
        widget=forms.CheckboxSelectMultiple,
    )
    amount_paid = forms.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.01"),
        label="Amount paid now",
        widget=forms.NumberInput(attrs={"class": "input", "step": "0.01"}),
    )
    method = forms.ChoiceField(
        choices=PaymentReceipt.Method.choices,
        initial=PaymentReceipt.Method.CASH,
        label="Method",
        widget=forms.Select(attrs={"class": "input"}),
    )
    reference_type = forms.ChoiceField(
        choices=PaymentReceipt.ReferenceType.choices,
        initial=PaymentReceipt.ReferenceType.NONE,
        required=False,
        label="Reference type",
        widget=forms.Select(attrs={"class": "input"}),
    )
    reference = forms.CharField(
        required=False,
        label="Reference",
        widget=forms.TextInput(attrs={"class": "input"}),
    )
    cheque_date = forms.DateField(
        required=False,
        label="Cheque date",
        widget=forms.DateInput(attrs={"class": "input", "type": "date"}),
    )
    bank_name = forms.CharField(
        required=False, max_length=100,
        label="Bank name",
        widget=forms.TextInput(attrs={"class": "input"}),
    )
    branch_name = forms.CharField(
        required=False, max_length=100,
        label="Branch",
        widget=forms.TextInput(attrs={"class": "input"}),
    )
    note = forms.CharField(
        required=False,
        label="Remarks",
        widget=forms.Textarea(attrs={"class": "input", "rows": 2}),
    )
    idempotency_key = forms.CharField(
        widget=forms.HiddenInput(), required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.initial.get("idempotency_key"):
            self.initial["idempotency_key"] = uuid.uuid4().hex

        today = timezone.localdate()
        self.fields["student"].queryset = (
            Student.objects
            .filter(is_active=True)
            .select_related("class_ref")
            .order_by("class_ref", "roll_no")
        )
        self.fields["billing_period"].queryset = (
            BillingPeriod.objects
            .filter(due_date__gte=today)
            .order_by("-start_date")
        )
        self.fields["categories"].queryset = (
            FeeCategory.objects
            .filter(status=FeeCategory.Status.ACTIVE)
            .order_by("name")
        )

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get("mode") or self.MODE_INVOICE
        student = cleaned.get("student")
        categories = cleaned.get("categories")
        period = cleaned.get("billing_period")
        amount = cleaned.get("amount_paid")
        method = cleaned.get("method")
        reference = (cleaned.get("reference") or "").strip()

        if mode == self.MODE_INVOICE:
            if not categories:
                self.add_error("categories",
                               "Select at least one category to create an invoice.")
                return cleaned
            if not period:
                self.add_error("billing_period",
                               "Choose a billing period to create an invoice.")
                return cleaned

            from finance.services.invoicing import _student_category_id, select_rules
            class_ref = student.class_ref
            try:
                student_category_id = _student_category_id(student)
            except Exception:
                student_category_id = None

            try:
                rules = select_rules(
                    class_ref=class_ref,
                    student_category_id=student_category_id,
                    period=period,
                )
            except Exception as e:
                self.add_error("categories", f"Could not look up fee rules: {e}")
                return cleaned

            rules_by_category = {}
            for rule in rules:
                rules_by_category.setdefault(rule.fee_category_id, rule)

            total = Decimal("0")
            breakdown = []
            for cat in categories:
                rule = rules_by_category.get(cat.pk)
                if rule is None:
                    self.add_error(
                        "categories",
                        f"No fee amount set for '{cat.name}' in {class_ref}. "
                        "Ask the accountant to configure it first.",
                    )
                    return cleaned
                total += rule.amount
                breakdown.append((cat, rule, rule.amount))

            cleaned["total_amount"] = total
            cleaned["breakdown"] = breakdown

            if amount > total:
                self.add_error("amount_paid",
                               f"Amount paid cannot exceed total {total}.")
                return cleaned

        # Provider-aware reference validation (applies to both modes).
        if method == PaymentReceipt.Method.CHEQUE:
            if not reference:
                self.add_error("reference",
                               "Cheque number is required for cheque payments.")
            if not cleaned.get("cheque_date"):
                self.add_error("cheque_date",
                               "Cheque date is required for cheque payments.")
            cleaned["reference_type"] = PaymentReceipt.ReferenceType.CHEQUE_NO
        elif method in (PaymentReceipt.Method.BANK_TRANSFER,
                        PaymentReceipt.Method.BKASH,
                        PaymentReceipt.Method.NAGAD,
                        PaymentReceipt.Method.ROCKET):
            if not reference:
                self.add_error("reference",
                               "A transaction/reference number is required for this method.")
            cleaned["reference_type"] = (
                PaymentReceipt.ReferenceType.TXN_ID
                if method != PaymentReceipt.Method.BANK_TRANSFER
                else PaymentReceipt.ReferenceType.REF_NO
            )

        if reference and method != PaymentReceipt.Method.CASH:
            dupe = PaymentReceipt.objects.filter(
                method=method,
                reference=reference,
                status=PaymentReceipt.Status.ACTIVE,
            )
            if dupe.exists():
                self.add_error(
                    "reference",
                    "Another active payment already uses this reference for this method.",
                )

        cleaned["mode"] = mode
        return cleaned


class AllocationForm(FinanceFormMixin, forms.Form):
    """Accountant form: allocate an existing payment to an invoice."""

    payment = forms.ModelChoiceField(
        queryset=None,
        label="Payment",
        widget=forms.Select(attrs={"class": "input"}),
    )
    invoice = forms.ModelChoiceField(
        queryset=None,
        label="Invoice",
        widget=forms.Select(attrs={"class": "input"}),
    )
    amount = forms.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.01"),
        label="Amount",
        widget=forms.NumberInput(attrs={"class": "input", "step": "0.01"}),
    )
    idempotency_key = forms.CharField(
        widget=forms.HiddenInput(), required=False,
    )

    def __init__(self, *args, student=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.student = student
        if not self.initial.get("idempotency_key"):
            self.initial["idempotency_key"] = uuid.uuid4().hex
        if student:
            from .models import StudentInvoice
            self.fields["payment"].queryset = PaymentReceipt.objects.filter(
                student=student, status=PaymentReceipt.Status.ACTIVE,
            ).order_by("-received_at")
            self.fields["invoice"].queryset = StudentInvoice.objects.filter(
                student=student, balance__gt=0,
            ).exclude(status=StudentInvoice.Status.CANCELLED).order_by("due_date")

    def clean(self):
        cleaned = super().clean()
        payment, invoice = cleaned.get("payment"), cleaned.get("invoice")
        amount = cleaned.get("amount")
        if not payment or not invoice or not amount:
            return cleaned
        if payment.student_id != invoice.student_id:
            self.add_error("invoice", "Payment and invoice belong to different students.")
        from finance.services.payments import available_credit
        credit = available_credit(payment.student)
        if amount > credit:
            self.add_error("amount", f"Amount exceeds available credit {credit}.")
        if amount > invoice.balance:
            self.add_error("amount", f"Amount exceeds invoice balance {invoice.balance}.")
        return cleaned