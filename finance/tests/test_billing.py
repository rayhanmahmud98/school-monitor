"""Fee amounts, discounts, invoicing, cancellation and adjustments."""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from finance.models import (DiscountRule, FeeCategory, FeeRule, InvoiceAdjustment, LedgerTransaction,
                            StudentDiscount, StudentInvoice)
from finance.services import discounts, fees, invoicing, ledger

from .helpers import (current_period, link_parent, make_category, make_class, make_student,
                      make_user, make_year, set_fee)

D = Decimal


class FeeAmountTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin", "ADMIN")
        self.year = make_year()
        self.cls = make_class(self.year)
        self.cat = make_category()

    def test_new_amount_creates_version_and_closes_previous(self):
        first = set_fee(self.cat, self.year, self.cls, "1000", self.admin)
        later = date(timezone.localdate().year, 7, 1)
        second = fees.set_amount(self.cat, self.year, self.cls, D("1200"), later, self.admin)
        first.refresh_from_db()
        self.assertEqual(second.supersedes, first)
        self.assertEqual(first.effective_to, date(later.year, 6, 30))

    def test_unchanged_amount_is_a_no_op(self):
        set_fee(self.cat, self.year, self.cls, "1000", self.admin)
        self.assertIsNone(set_fee(self.cat, self.year, self.cls, "1000", self.admin))
        self.assertEqual(FeeRule.objects.count(), 1)

    def test_rejects_zero_and_inactive_category_and_wrong_year_class(self):
        with self.assertRaises(fees.FeeError):
            set_fee(self.cat, self.year, self.cls, "0", self.admin)
        other = make_class(self.year, name="Class 6")
        other.academic_year = "1999"
        other.save()
        with self.assertRaises(fees.FeeError):
            set_fee(self.cat, self.year, other, "10", self.admin)
        fees.set_category_status(self.cat, "INACTIVE", self.admin)
        with self.assertRaises(fees.FeeError):
            set_fee(self.cat, self.year, self.cls, "10", self.admin)

    def test_used_category_cannot_be_deleted_but_unused_can(self):
        set_fee(self.cat, self.year, self.cls, "1000", self.admin)
        with self.assertRaises(fees.FeeError):
            fees.delete_category(self.cat, self.admin)
        unused = make_category(code="TMP", name="Temporary")
        fees.delete_category(unused, self.admin)
        self.assertFalse(FeeCategory.objects.filter(pk=unused.pk).exists())

    def test_code_is_case_insensitively_unique(self):
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                FeeCategory.objects.create(code="tuition", name="Dup")


class InvoicingTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin", "ADMIN")
        self.year = make_year()
        self.cls = make_class(self.year)
        self.student = make_student(self.cls, 1)
        self.cat = make_category()
        set_fee(self.cat, self.year, self.cls, "1500", self.admin)
        self.period = current_period(self.year)

    def test_generation_creates_balanced_invoice_and_ledger(self):
        result = invoicing.generate_bulk(self.period, self.admin)
        self.assertEqual(len(result.created), 1)
        inv = StudentInvoice.objects.get()
        self.assertEqual((inv.original_amount, inv.net_payable, inv.balance), (D("1500"), D("1500"), D("1500")))
        self.assertEqual(inv.category_name_snapshot, "Tuition fee")
        lines = inv.issue_tx.lines.all()
        self.assertEqual(sum(l.debit for l in lines), sum(l.credit for l in lines))
        self.assertEqual(ledger.account_balance(ledger.account("RECEIVABLE")), D("1500"))
        self.assertEqual(ledger.account_balance(ledger.account("FEE_INCOME")), D("-1500"))

    def test_generation_is_idempotent(self):
        invoicing.generate_bulk(self.period, self.admin)
        again = invoicing.generate_bulk(self.period, self.admin)
        self.assertEqual((len(again.created), again.skipped), (0, 1))
        self.assertEqual(StudentInvoice.objects.count(), 1)
        self.assertEqual(LedgerTransaction.objects.filter(tx_type="invoice_issue").count(), 1)

    def test_renaming_category_does_not_change_history(self):
        invoicing.generate_bulk(self.period, self.admin)
        self.cat.name = "Renamed"
        self.cat.save()
        self.assertEqual(StudentInvoice.objects.get().category_name_snapshot, "Tuition fee")

    def test_new_amount_does_not_touch_issued_invoice(self):
        invoicing.generate_bulk(self.period, self.admin)
        fees.set_amount(self.cat, self.year, self.cls, D("2000"), timezone.localdate(), self.admin)
        self.assertEqual(StudentInvoice.objects.get().original_amount, D("1500"))

    def test_inactive_category_is_not_billed(self):
        fees.set_category_status(self.cat, "INACTIVE", self.admin)
        result = invoicing.generate_bulk(self.period, self.admin)
        self.assertEqual(len(result.created), 0)

    def test_future_period_cannot_be_invoiced(self):
        from finance.models import BillingPeriod
        future = BillingPeriod.objects.filter(academic_year=self.year, issue_date__gt=timezone.localdate()).first()
        if future is None:
            self.skipTest("today is in the last month of the year")
        with self.assertRaises(invoicing.InvoiceError):
            invoicing.generate_bulk(future, self.admin)

    def test_student_in_other_year_is_not_billed(self):
        other = make_class(self.year, name="Class 9")
        other.academic_year = "1999-2000"
        other.save()
        make_student(other, 1, first="Old")
        result = invoicing.generate_bulk(self.period, self.admin)
        self.assertEqual(len(result.created), 1)

    def test_enrollment_triggers_invoices(self):
        newcomer = None
        with self.captureOnCommitCallbacks(execute=True):
            newcomer = make_student(self.cls, 2, first="New")
        self.assertTrue(StudentInvoice.objects.filter(student=newcomer).exists())

    def test_cancel_reverses_ledger_and_allows_regeneration(self):
        invoicing.generate_bulk(self.period, self.admin)
        inv = StudentInvoice.objects.get()
        invoicing.cancel_invoice(inv.pk, "issued by mistake", self.admin)
        inv.refresh_from_db()
        self.assertEqual(inv.status, "CANCELLED")
        self.assertEqual(ledger.account_balance(ledger.account("RECEIVABLE")), 0)
        self.assertEqual(ledger.account_balance(ledger.account("FEE_INCOME")), 0)
        again = invoicing.generate_bulk(self.period, self.admin)
        self.assertEqual(len(again.created), 1)

    def test_cancel_needs_reason_and_cannot_repeat(self):
        invoicing.generate_bulk(self.period, self.admin)
        inv = StudentInvoice.objects.get()
        with self.assertRaises(invoicing.InvoiceError):
            invoicing.cancel_invoice(inv.pk, "  ", self.admin)
        invoicing.cancel_invoice(inv.pk, "ok", self.admin)
        with self.assertRaises(invoicing.InvoiceError):
            invoicing.cancel_invoice(inv.pk, "again", self.admin)

    def test_adjustments_update_totals_and_ledger(self):
        invoicing.generate_bulk(self.period, self.admin)
        inv = StudentInvoice.objects.get()
        invoicing.add_adjustment(inv.pk, "DISCOUNT", D("100"), "hardship", self.admin)
        invoicing.add_adjustment(inv.pk, "PENALTY", D("50"), "late", self.admin)
        invoicing.add_adjustment(inv.pk, "CORRECTION_DOWN", D("25"), "typo", self.admin)
        inv.refresh_from_db()
        self.assertEqual(inv.original_amount, D("1475"))
        self.assertEqual(inv.net_payable, D("1475") - D("100") + D("50"))
        self.assertEqual(inv.balance, inv.net_payable)
        self.assertEqual(ledger.account_balance(ledger.account("RECEIVABLE")), inv.balance)
        self.assertEqual(InvoiceAdjustment.objects.filter(invoice=inv).count(), 3)

    def test_reduction_cannot_exceed_balance(self):
        invoicing.generate_bulk(self.period, self.admin)
        inv = StudentInvoice.objects.get()
        with self.assertRaises(invoicing.InvoiceError):
            invoicing.add_adjustment(inv.pk, "WAIVER", D("1500.01"), "too much", self.admin)
        invoicing.add_adjustment(inv.pk, "WAIVER", D("1500"), "full waiver", self.admin)
        inv.refresh_from_db()
        self.assertEqual((inv.balance, inv.status), (D("0"), "PAID"))

    def test_cancel_after_adjustments_still_zeroes_the_ledger(self):
        invoicing.generate_bulk(self.period, self.admin)
        inv = StudentInvoice.objects.get()
        invoicing.add_adjustment(inv.pk, "DISCOUNT", D("100"), "a", self.admin)
        invoicing.add_adjustment(inv.pk, "WAIVER", D("200"), "b", self.admin)
        invoicing.add_adjustment(inv.pk, "PENALTY", D("40"), "c", self.admin)
        invoicing.cancel_invoice(inv.pk, "undo all", self.admin)
        for key in ("RECEIVABLE", "FEE_INCOME", "DISCOUNTS", "WAIVERS", "LATE_FEE_INCOME"):
            self.assertEqual(ledger.account_balance(ledger.account(key)), 0, key)


class DiscountTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin", "ADMIN")
        self.year = make_year()
        self.cls = make_class(self.year)
        self.cat = make_category()
        self.student = make_student(self.cls, 1)
        self.start = date(timezone.localdate().year, 1, 1)

    def rule(self, **kw):
        defaults = dict(name="r", kind="MANUAL", value_type="PERCENT", value=D("10"),
                        effective_from=self.start)
        defaults.update(kw)
        return DiscountRule.objects.create(**defaults)

    def award(self, rule):
        return StudentDiscount.objects.create(student=self.student, rule=rule, awarded_by=self.admin,
                                              approval_status="APPROVED", valid_from=self.start)

    def resolve(self, amount="1000"):
        return discounts.resolve(self.student, self.cat, timezone.localdate(), D(amount),
                                 academic_year=self.year)

    def test_percent_and_fixed_apply_sequentially(self):
        self.award(self.rule(name="ten", priority=1))                                   # 10% of 1000 = 100
        self.award(self.rule(name="fixed", value_type="FIXED", value=D("50"), priority=2))
        lines = self.resolve()
        self.assertEqual([l.amount for l in lines], [D("100.00"), D("50.00")])

    def test_second_percentage_applies_to_the_remainder(self):
        self.award(self.rule(name="a", priority=1, value=D("10")))
        self.award(self.rule(name="b", priority=2, value=D("10")))
        self.assertEqual([l.amount for l in self.resolve()], [D("100.00"), D("90.00")])

    def test_stack_group_keeps_only_the_best(self):
        self.award(self.rule(name="small", stack_group="g", value=D("5")))
        self.award(self.rule(name="big", stack_group="g", value=D("20")))
        lines = self.resolve()
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].rule.name, "big")

    def test_never_below_zero_and_max_amount(self):
        self.award(self.rule(name="huge", value_type="FIXED", value=D("5000")))
        self.assertEqual(self.resolve()[0].amount, D("1000.00"))
        capped = self.rule(name="capped", value_type="FIXED", value=D("400"), max_amount=D("150"), priority=0)
        self.award(capped)
        self.assertEqual(self.resolve()[0].amount, D("150.00"))

    def test_pending_and_expired_awards_are_ignored(self):
        pending = self.rule(name="pending")
        StudentDiscount.objects.create(student=self.student, rule=pending, approval_status="PENDING",
                                       valid_from=self.start)
        expired = self.rule(name="expired")
        StudentDiscount.objects.create(student=self.student, rule=expired, approval_status="APPROVED",
                                       valid_from=self.start, valid_to=date(self.start.year, 1, 2))
        self.assertEqual(self.resolve(), [])

    def test_sibling_rule_is_automatic_from_the_second_child(self):
        self.rule(name="sib", kind="SIBLING", sibling_rank_from=2, value=D("10"))
        parent = make_user("p1", "PARENT")
        elder = make_student(self.cls, 2, first="Elder", admission_date=date(2020, 1, 1))
        link_parent(parent, elder)
        link_parent(parent, self.student)
        self.student.admission_date = date(2024, 1, 1)
        self.student.save()
        self.assertEqual(len(self.resolve()), 1)           # younger child gets it
        self.assertEqual(len(discounts.resolve(elder, self.cat, timezone.localdate(), D("1000"),
                                               academic_year=self.year)), 0)

    def test_annual_cap(self):
        r = self.rule(name="capped", value_type="FIXED", value=D("300"), annual_cap=D("500"))
        self.award(r)
        first = self.resolve()
        self.assertEqual(first[0].amount, D("300.00"))
        set_fee(self.cat, self.year, self.cls, "1000", self.admin)
        period = current_period(self.year)
        invoicing.generate_bulk(period, self.admin)          # uses 300 of the 500 cap
        again = self.resolve()
        self.assertEqual(again[0].amount, D("200.00"))

    def test_full_scholarship_makes_a_zero_invoice(self):
        self.award(self.rule(name="full", value=D("100")))
        set_fee(self.cat, self.year, self.cls, "800", self.admin)
        invoicing.generate_bulk(current_period(self.year), self.admin)
        inv = StudentInvoice.objects.get()
        self.assertEqual((inv.net_payable, inv.status), (D("0"), "PAID"))
        self.assertEqual(ledger.account_balance(ledger.account("RECEIVABLE")), 0)
