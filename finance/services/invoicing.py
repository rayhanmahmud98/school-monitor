"""Invoice generation, cancellation and adjustment. Idempotent and ledger-backed."""
import logging
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from ..adapters import school
from ..models import (FREQUENCY_FOR_KIND, BillingPeriod, DiscountRule, FeeCategory, FeeRule,
                      InvoiceAdjustment, StudentFeeProfile, StudentInvoice)
from ..money import ZERO, money
from . import audit, discounts, ledger
from .numbering import next_number
from .periods import PeriodClosed

logger = logging.getLogger(__name__)


class InvoiceError(Exception):
    pass


@dataclass
class RunResult:
    created: list = field(default_factory=list)   # invoice numbers
    skipped: int = 0                              # already invoiced
    failed: list = field(default_factory=list)    # (student label, reason)


def select_rules(*, class_ref, student_category_id, period):
    """The one best FeeRule per category for this class/student/period."""
    on = period.start_date
    qs = (FeeRule.objects
          .filter(academic_year=period.academic_year, is_active=True,
                  frequency=FREQUENCY_FOR_KIND[period.kind], effective_from__lte=on,
                  fee_category__status=FeeCategory.Status.ACTIVE)
          .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=on))
          .filter(Q(class_ref=class_ref) | Q(class_ref__isnull=True))
          .filter(Q(student_category__isnull=True)
                  | Q(student_category_id=student_category_id or 0))
          .select_related("fee_category"))
    best = {}
    for rule in qs:
        score = (rule.class_ref_id is not None, rule.student_category_id is not None,
                 rule.effective_from)
        held = best.get(rule.fee_category_id)
        if held is None or score > held[0]:
            best[rule.fee_category_id] = (score, rule)
    return [rule for _, rule in best.values()]


def _student_category_id(student):
    return (StudentFeeProfile.objects.filter(student=student)
            .values_list("category_id", flat=True).first())


@transaction.atomic
def _build_invoice(*, student, rule, period, actor, enrollment, request):
    today = timezone.localdate()
    category = rule.fee_category
    lines = discounts.resolve(student, category, period.issue_date, rule.amount,
                              academic_year=period.academic_year)
    original = money(rule.amount)
    discount_total = sum((ln.amount for ln in lines), ZERO)
    net = original - discount_total
    waiver_total = sum((ln.amount for ln in lines if ln.rule.kind == DiscountRule.Kind.WAIVER), ZERO)

    invoice = StudentInvoice.objects.create(
        invoice_no=next_number("invoice", today), student=student, enrollment=enrollment,
        fee_category=category, fee_rule=rule, billing_period=period,
        description_snapshot=f"{category.name} - {period.label}"[:200],
        category_code_snapshot=category.code, category_name_snapshot=category.name,
        original_amount=original, discount_total=discount_total, penalty_total=ZERO,
        net_payable=net, paid_total=ZERO, balance=net, issue_date=today, due_date=period.due_date,
        status=StudentInvoice.Status.PAID if net == 0 else StudentInvoice.Status.ISSUED,
        issued_by=actor if getattr(actor, "is_authenticated", False) else None)

    tx = ledger.post(
        tx_type="invoice_issue", posting_date=today, actor=actor,
        description=f"{invoice.invoice_no} {student.full_name}",
        source=("invoice", invoice.pk),
        lines=[
            {"account": "RECEIVABLE", "debit": net, "student": student, "fee_category": category},
            {"account": "DISCOUNTS", "debit": discount_total - waiver_total,
             "student": student, "fee_category": category},
            {"account": "WAIVERS", "debit": waiver_total, "student": student, "fee_category": category},
            {"account": "FEE_INCOME", "credit": original, "student": student, "fee_category": category},
        ])
    invoice.issue_tx = tx
    invoice.save(update_fields=["issue_tx"])

    for ln in lines:
        kind = (InvoiceAdjustment.Kind.WAIVER if ln.rule.kind == DiscountRule.Kind.WAIVER
                else InvoiceAdjustment.Kind.DISCOUNT)
        InvoiceAdjustment.objects.create(
            invoice=invoice, kind=kind, amount=-ln.amount, discount_rule=ln.rule,
            student_discount=ln.student_discount, reason=ln.note, ledger_tx=tx,
            created_by=actor if getattr(actor, "is_authenticated", False) else None)

    audit.record(actor=actor, event_type="invoice.issued", obj=invoice,
                 new={"invoice_no": invoice.invoice_no, "student": student.student_id,
                      "category": category.code, "original": str(original),
                      "discount": str(discount_total), "net": str(net)},
                 refs={"ledger_tx": tx.pk}, request=request)
    return invoice


def create_invoice(*, student, rule, period, actor, enrollment=None, request=None):
    """Create one invoice, or return None if this student/rule/period is already invoiced."""
    exists = (StudentInvoice.objects
              .filter(student=student, fee_rule=rule, billing_period=period)
              .exclude(status=StudentInvoice.Status.CANCELLED).exists())
    if exists:
        return None
    try:
        return _build_invoice(student=student, rule=rule, period=period, actor=actor,
                              enrollment=enrollment, request=request)
    except IntegrityError:   # lost a race with another request: the unique index protects us
        return None


def generate_for_student(student, period, actor, *, class_ref=None, enrollment=None, request=None):
    """Invoices for one student in one billing period. Returns (created, skipped)."""
    class_ref = class_ref or student.class_ref
    if class_ref.academic_year != period.academic_year.name:
        return [], 0
    created, skipped = [], 0
    for rule in select_rules(class_ref=class_ref, student_category_id=_student_category_id(student),
                             period=period):
        invoice = create_invoice(student=student, rule=rule, period=period, actor=actor,
                                 enrollment=enrollment, request=request)
        if invoice is None:
            skipped += 1
        else:
            created.append(invoice)
    return created, skipped


def generate_bulk(period, actor, *, class_ref=None, request=None):
    """Bulk run for a period (optionally one class). Safe to repeat."""
    today = timezone.localdate()
    if period.issue_date > today:
        raise InvoiceError(f"{period} cannot be invoiced before {period.issue_date}.")
    if class_ref is not None and class_ref.academic_year != period.academic_year.name:
        raise InvoiceError("That class does not belong to the period's academic year.")
    result = RunResult()
    for student in school.active_students_for_year(period.academic_year.name, class_ref):
        try:
            created, skipped = generate_for_student(student, period, actor, request=request)
        except PeriodClosed:
            raise
        except Exception as exc:  # noqa: BLE001 - isolate one student's failure
            logger.exception("Invoice generation failed for %s", student)
            result.failed.append((student.full_name, str(exc)[:200]))
            continue
        result.created.extend(i.invoice_no for i in created)
        result.skipped += skipped
    audit.record(actor=actor, event_type="invoice.bulk_generated", object_type="BillingPeriod",
                 object_id=str(period.pk),
                 new={"period": str(period), "class": str(class_ref) if class_ref else "all",
                      "created": len(result.created), "skipped": result.skipped,
                      "failed": len(result.failed)}, request=request)
    return result


def preview_bulk(period, *, class_ref=None):
    """What a bulk run would do, without writing anything."""
    totals = {"students": 0, "to_create": 0, "existing": 0, "gross": ZERO, "discount": ZERO}
    for student in school.active_students_for_year(period.academic_year.name, class_ref):
        rules = select_rules(class_ref=student.class_ref,
                             student_category_id=_student_category_id(student), period=period)
        if not rules:
            continue
        totals["students"] += 1
        for rule in rules:
            exists = (StudentInvoice.objects.filter(student=student, fee_rule=rule, billing_period=period)
                      .exclude(status=StudentInvoice.Status.CANCELLED).exists())
            if exists:
                totals["existing"] += 1
                continue
            lines = discounts.resolve(student, rule.fee_category, period.issue_date, rule.amount,
                                      academic_year=period.academic_year)
            totals["to_create"] += 1
            totals["gross"] += money(rule.amount)
            totals["discount"] += sum((ln.amount for ln in lines), ZERO)
    totals["net"] = totals["gross"] - totals["discount"]
    return totals


def generate_for_enrollment(enrollment_pk, actor=None):
    """Triggered when a student is enrolled: invoices for ONE_TIME periods and the period in progress."""
    from ..adapters.school import Enrollment
    enrollment = Enrollment.objects.select_related("student", "class_ref").get(pk=enrollment_pk)
    if not enrollment.is_current or not enrollment.student.is_active:
        return []
    today = timezone.localdate()
    try:
        year = school.academic_year_for_class(enrollment.class_ref)
    except school.AcademicYearMismatch:
        logger.warning("No AcademicYear matches class %s; no invoices generated.", enrollment.class_ref)
        return []
    periods = (BillingPeriod.objects.filter(academic_year=year, issue_date__lte=today)
               .filter(Q(kind=BillingPeriod.Kind.ONE_TIME) | Q(end_date__gte=today)))
    created = []
    for period in periods:
        new, _ = generate_for_student(enrollment.student, period, actor,
                                      class_ref=enrollment.class_ref, enrollment=enrollment)
        created.extend(new)
    return created


# ---- cancel and adjust -----------------------------------------------------------
@transaction.atomic
def cancel_invoice(invoice_pk, reason, actor, request=None):
    invoice = StudentInvoice.objects.select_for_update().select_related("student").get(pk=invoice_pk)
    if invoice.status == StudentInvoice.Status.CANCELLED:
        raise InvoiceError("This invoice is already cancelled.")
    if invoice.paid_total > 0:
        raise InvoiceError("Payments are allocated to this invoice. Reverse them first.")
    if not reason.strip():
        raise InvoiceError("A reason is required.")

    sums = {k: ZERO for k in ("DISCOUNT", "WAIVER")}
    for adj in invoice.adjustments.filter(kind__in=sums):
        sums[adj.kind] += -adj.amount
    discounts_acct = invoice.discount_total - sums["WAIVER"]
    # Reverse the net effect of everything posted for this invoice.
    tx = ledger.post(
        tx_type="invoice_cancel", posting_date=timezone.localdate(), actor=actor,
        description=f"Cancel {invoice.invoice_no}: {reason}", source=("invoice", invoice.pk),
        reverses=None,
        lines=[
            {"account": "FEE_INCOME", "debit": invoice.original_amount, "student": invoice.student,
             "fee_category": invoice.fee_category},
            {"account": "LATE_FEE_INCOME", "debit": invoice.penalty_total, "student": invoice.student,
             "fee_category": invoice.fee_category},
            {"account": "RECEIVABLE", "credit": invoice.net_payable, "student": invoice.student,
             "fee_category": invoice.fee_category},
            {"account": "DISCOUNTS", "credit": discounts_acct, "student": invoice.student,
             "fee_category": invoice.fee_category},
            {"account": "WAIVERS", "credit": sums["WAIVER"], "student": invoice.student,
             "fee_category": invoice.fee_category},
        ])
    old_status = invoice.status
    invoice.status = StudentInvoice.Status.CANCELLED
    invoice.cancelled_reason = reason
    invoice.save(update_fields=["status", "cancelled_reason"])
    audit.record(actor=actor, event_type="invoice.cancelled", obj=invoice,
                 old={"status": old_status}, new={"status": invoice.status}, reason=reason,
                 refs={"ledger_tx": tx.pk}, request=request)
    return invoice


ADJUSTMENT_CHOICES = {
    # key: (adjustment kind, sign, label)
    "DISCOUNT": (InvoiceAdjustment.Kind.DISCOUNT, -1, "Discount (reduces amount)"),
    "WAIVER": (InvoiceAdjustment.Kind.WAIVER, -1, "Waiver (reduces amount)"),
    "PENALTY": (InvoiceAdjustment.Kind.PENALTY, +1, "Penalty (increases amount)"),
    "CORRECTION_UP": (InvoiceAdjustment.Kind.CORRECTION, +1, "Correction: increase"),
    "CORRECTION_DOWN": (InvoiceAdjustment.Kind.CORRECTION, -1, "Correction: decrease"),
}


@transaction.atomic
def add_adjustment(invoice_pk, choice, amount, reason, actor, request=None):
    if choice not in ADJUSTMENT_CHOICES:
        raise InvoiceError("Unknown adjustment type.")
    amount = money(amount)
    if amount <= 0:
        raise InvoiceError("Enter an amount greater than zero.")
    if not reason.strip():
        raise InvoiceError("A reason is required.")
    kind, sign, _label = ADJUSTMENT_CHOICES[choice]
    invoice = StudentInvoice.objects.select_for_update().select_related("student", "fee_category").get(pk=invoice_pk)
    if invoice.status == StudentInvoice.Status.CANCELLED:
        raise InvoiceError("A cancelled invoice cannot be adjusted.")
    if sign < 0 and amount > invoice.balance:
        raise InvoiceError(f"A reduction cannot exceed the outstanding balance ({invoice.balance}).")

    signed = amount * sign
    before = {"original": str(invoice.original_amount), "discount": str(invoice.discount_total),
              "penalty": str(invoice.penalty_total), "net": str(invoice.net_payable),
              "balance": str(invoice.balance)}
    student, cat = invoice.student, invoice.fee_category
    if choice == "DISCOUNT":
        invoice.discount_total += amount
        lines = [{"account": "DISCOUNTS", "debit": amount}, {"account": "RECEIVABLE", "credit": amount}]
    elif choice == "WAIVER":
        invoice.discount_total += amount
        lines = [{"account": "WAIVERS", "debit": amount}, {"account": "RECEIVABLE", "credit": amount}]
    elif choice == "PENALTY":
        invoice.penalty_total += amount
        lines = [{"account": "RECEIVABLE", "debit": amount}, {"account": "LATE_FEE_INCOME", "credit": amount}]
    elif choice == "CORRECTION_UP":
        invoice.original_amount += amount
        lines = [{"account": "RECEIVABLE", "debit": amount}, {"account": "FEE_INCOME", "credit": amount}]
    else:  # CORRECTION_DOWN
        if amount > invoice.original_amount:
            raise InvoiceError("A correction cannot take the original amount below zero.")
        invoice.original_amount -= amount
        lines = [{"account": "FEE_INCOME", "debit": amount}, {"account": "RECEIVABLE", "credit": amount}]

    for ln in lines:
        ln["student"], ln["fee_category"] = student, cat
    invoice.net_payable = invoice.original_amount - invoice.discount_total + invoice.penalty_total
    invoice.balance = invoice.net_payable - invoice.paid_total
    if invoice.balance == 0:
        invoice.status = StudentInvoice.Status.PAID
    elif invoice.paid_total > 0:
        invoice.status = StudentInvoice.Status.PARTIAL
    else:
        invoice.status = StudentInvoice.Status.ISSUED

    tx = ledger.post(tx_type="invoice_adjustment", posting_date=timezone.localdate(), actor=actor,
                     description=f"{invoice.invoice_no} {choice}: {reason}", lines=lines,
                     source=("invoice", invoice.pk))
    invoice.save(update_fields=["original_amount", "discount_total", "penalty_total",
                                "net_payable", "balance", "status"])
    adjustment = InvoiceAdjustment.objects.create(
        invoice=invoice, kind=kind, amount=signed, reason=reason, ledger_tx=tx,
        created_by=actor if getattr(actor, "is_authenticated", False) else None)
    audit.record(actor=actor, event_type="invoice.adjusted", obj=invoice, old=before,
                 new={"choice": choice, "amount": str(signed), "net": str(invoice.net_payable),
                      "balance": str(invoice.balance)},
                 reason=reason, refs={"adjustment": adjustment.pk, "ledger_tx": tx.pk}, request=request)
    return adjustment
