"""Discount resolution. Pure(ish) and table-testable: no writes happen here."""
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Q, Sum

from ..adapters import school
from ..models import DiscountRule, InvoiceAdjustment, StudentDiscount
from ..money import ZERO, money


@dataclass
class DiscountLine:
    rule: DiscountRule
    student_discount: StudentDiscount | None
    amount: Decimal      # always positive: how much the payable is reduced
    note: str


def _rule_amount(rule, remaining):
    if rule.value_type == DiscountRule.ValueType.PERCENT:
        raw = remaining * rule.value / Decimal("100")
    else:
        raw = rule.value
    amount = money(raw)
    if rule.max_amount is not None:
        amount = min(amount, money(rule.max_amount))
    return min(amount, remaining)


def _used_this_year(rule, student, academic_year):
    agg = InvoiceAdjustment.objects.filter(
        discount_rule=rule, invoice__student=student,
        invoice__billing_period__academic_year=academic_year,
    ).exclude(invoice__status="CANCELLED").aggregate(total=Sum("amount"))
    return money(-(agg["total"] or 0))


def candidates(student, category, on_date):
    """(rule, student_discount|None) pairs the student is eligible for on `on_date`."""
    rule_filter = (
        Q(is_active=True, effective_from__lte=on_date)
        & (Q(effective_to__isnull=True) | Q(effective_to__gte=on_date))
        & (Q(categories__isnull=True) | Q(categories=category))
    )
    found = []
    awards = (StudentDiscount.objects
              .filter(student=student, approval_status=StudentDiscount.Approval.APPROVED,
                      valid_from__lte=on_date)
              .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=on_date))
              .select_related("rule"))
    seen_rules = set()
    for award in awards:
        rule = award.rule
        if rule.pk in seen_rules or rule.kind == DiscountRule.Kind.SIBLING:
            continue
        if DiscountRule.objects.filter(rule_filter, pk=rule.pk).exists():
            found.append((rule, award))
            seen_rules.add(rule.pk)

    sibling_rules = (DiscountRule.objects.filter(rule_filter, kind=DiscountRule.Kind.SIBLING,
                                                 sibling_rank_from__isnull=False).distinct())
    if sibling_rules:
        rank = school.sibling_rank(student)
        for rule in sibling_rules:
            if rank >= rule.sibling_rank_from:
                found.append((rule, None))
    found.sort(key=lambda pair: (pair[0].priority, pair[0].pk))
    return found


def resolve(student, category, on_date, base_amount, academic_year=None):
    """Return the DiscountLines for one invoice, applied sequentially on the remaining amount.

    Rules sharing a non-empty stack_group do not stack: the best of them wins.
    A discount never takes the payable below zero.
    """
    remaining = money(base_amount)
    groups, order = {}, []
    for rule, award in candidates(student, category, on_date):
        key = rule.stack_group or f"__solo_{rule.pk}"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((rule, award))

    lines = []
    for key in order:
        best = None
        for rule, award in groups[key]:
            amount = _rule_amount(rule, remaining)
            if rule.annual_cap is not None and academic_year is not None:
                left = money(rule.annual_cap) - _used_this_year(rule, student, academic_year)
                amount = min(amount, max(left, ZERO))
            if amount > 0 and (best is None or amount > best.amount):
                best = DiscountLine(rule=rule, student_discount=award, amount=amount, note=rule.name)
        if best is not None:
            lines.append(best)
            remaining -= best.amount
    return lines
