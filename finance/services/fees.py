"""Fee categories and fee amounts (the matrix)."""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q

from ..adapters.school import Class

from ..models import FeeCategory, FeeRule, LedgerLine, StudentInvoice
from ..money import money
from . import audit


class FeeError(Exception):
    pass


# ---- categories ----------------------------------------------------------------
def category_usage(category):
    return {
        "Fee rules": FeeRule.objects.filter(fee_category=category).count(),
        "Invoices": StudentInvoice.objects.filter(fee_category=category).count(),
        "Ledger lines": LedgerLine.objects.filter(fee_category=category).count(),
        "Installment options": category.installment_options.count(),
        "Discount rules": category.discount_rules.count(),
    }


def category_deletable(category):
    return sum(category_usage(category).values()) == 0


@transaction.atomic
def set_category_status(category, status, actor, request=None):
    old = category.status
    if old == status:
        return category
    category.status = status
    category.save(update_fields=["status", "updated_at"])
    audit.record(actor=actor, event_type="feecategory.status_changed", obj=category,
                 old={"status": old}, new={"status": status}, request=request)
    return category


@transaction.atomic
def delete_category(category, actor, request=None):
    if not category_deletable(category):
        raise FeeError("This category is used by financial records. Archive it instead.")
    snap = audit.snapshot(category)
    pk = category.pk
    category.delete()
    audit.record(actor=actor, event_type="feecategory.deleted", object_type="FeeCategory",
                 object_id=str(pk), old=snap, request=request)


# ---- fee amounts ----------------------------------------------------------------
def current_rule(category, year, class_ref, on_date):
    """Latest class-specific rule (all-student-categories) in force on `on_date`."""
    return (FeeRule.objects
            .filter(fee_category=category, academic_year=year, class_ref=class_ref,
                    student_category__isnull=True, is_active=True, effective_from__lte=on_date)
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=on_date))
            .order_by("-effective_from").first())


def matrix_data(year, on_date):
    """Categories x classes grid of the amounts in force on `on_date`."""
    categories = list(FeeCategory.objects.filter(status=FeeCategory.Status.ACTIVE)
                      .order_by("sort_order", "name"))
    classes = list(Class.objects.filter(academic_year=year.name).order_by("name", "section"))
    cells = {}
    rules = (FeeRule.objects
             .filter(academic_year=year, class_ref__in=classes, student_category__isnull=True,
                     is_active=True, effective_from__lte=on_date,
                     fee_category__in=categories)
             .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=on_date))
             .order_by("effective_from"))
    for rule in rules:
        cells[(rule.fee_category_id, rule.class_ref_id)] = rule
    return categories, classes, cells


@transaction.atomic
def set_amount(category, year, class_ref, amount, effective_from, actor, request=None):
    """Set the amount for a category in a class. Creates a new dated version; issued
    invoices are never touched. Returns the new/updated rule, or None if unchanged."""
    amount = money(amount)
    if amount <= 0:
        raise FeeError("Fee amounts must be greater than zero.")
    if category.status != FeeCategory.Status.ACTIVE:
        raise FeeError(f"{category.name} is not active.")
    if class_ref.academic_year != year.name:
        raise FeeError(f"{class_ref} does not belong to academic year {year}.")

    current = current_rule(category, year, class_ref, effective_from)
    if current and current.amount == amount:
        return None

    same_day = FeeRule.objects.filter(
        fee_category=category, academic_year=year, class_ref=class_ref,
        student_category__isnull=True, frequency=category.default_frequency,
        effective_from=effective_from).first()
    if same_day:  # same effective date: amend that version in place, with an audit trail
        old = {"amount": str(same_day.amount)}
        same_day.amount = amount
        same_day.is_active = True
        same_day.save(update_fields=["amount", "is_active"])
        audit.record(actor=actor, event_type="feerule.amount_changed", obj=same_day,
                     old=old, new={"amount": str(amount)}, request=request)
        return same_day

    rule = FeeRule.objects.create(
        fee_category=category, academic_year=year, class_ref=class_ref,
        frequency=category.default_frequency, amount=amount, effective_from=effective_from,
        supersedes=current, created_by=actor)
    if current and (current.effective_to is None or current.effective_to >= effective_from):
        current.effective_to = effective_from - timedelta(days=1)
        current.save(update_fields=["effective_to"])
    audit.record(actor=actor, event_type="feerule.amount_set", obj=rule,
                 old={"amount": str(current.amount)} if current else None,
                 new={"amount": str(amount), "effective_from": str(effective_from),
                      "class": str(class_ref), "category": category.code}, request=request)
    return rule


def increase(value, percent):
    return money(Decimal(value) * (Decimal("1") + Decimal(str(percent)) / Decimal("100")))


def amount_for(category, class_ref, period):
    """Return the active fee amount for a (category, class) as of the period."""
    from finance.models import FeeRule
    from django.utils import timezone
    from django.db.models import Q
    
    date = period.start_date if period else timezone.localdate()
    rule = (
        FeeRule.objects
        .filter(
            fee_category=category, # Change to `category=` if your model uses that
            class_ref=class_ref,
            effective_from__lte=date,
            is_active=True,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=date))
        .order_by("-effective_from")
        .first()
    )
    return rule.amount if rule else None # Change `amount` to `net_amount` if needed