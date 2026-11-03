"""Payment-First, Invoice-Later workflow — permanent regression tests."""
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.test import TestCase
from pypdf import PdfReader

from academics.models import AcademicYear
from accounts.models import User
from finance.constants import GROUPS, ACCOUNTANT, CLERK, AUDITOR
from finance.models import (
    BillingPeriod, FeeCategory, FeeRule, PaymentAllocation, PaymentReceipt,
    StudentInvoice,
)
from finance.pdf import render_receipt_pdf
from finance.services import payments
from students.models import Class, Student


# --------------------------------------------------------------------------- fixtures

def _user(username, role):
    u = User.objects.create_user(username=username, password="x")
    u.role = role
    u.save()
    return u


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.year = AcademicYear.objects.create(
            name="2026-2027", is_current=True,
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
        )
        cls.cls = Class.objects.create(name="10", section="A", academic_year=cls.year.name)
        cls.student = Student.objects.create(
            full_name="Test Student", student_id="STU-TEST-0001",
            roll_no="1",
            class_ref=cls.cls, is_active=True,
        )
        cls.clerk = _user("clerk_t", User.Role.CLERK)
        cls.acct = _user("acct_t", User.Role.ACCOUNTANT)
        cls.auditor = _user("aud_t", User.Role.AUDITOR)

        cls.cat = FeeCategory.objects.create(
            code="TUI", name="Tuition", status=FeeCategory.Status.ACTIVE,
        )
        cls.period = BillingPeriod.objects.create(
            academic_year=cls.year, kind=BillingPeriod.Kind.MONTH, label="2026-03",
            start_date=date(2026, 3, 1), end_date=date(2026, 3, 31),
            issue_date=date(2026, 3, 1), due_date=date(2026, 3, 31),
        )
        cls.rule = FeeRule.objects.create(
            fee_category=cls.cat, academic_year=cls.year, class_ref=cls.cls,
            frequency="MONTHLY", amount=Decimal("500.00"),
            effective_from=date(2026, 1, 1), is_active=True,
        )

    def _fresh_invoice(self, balance="500.00"):
        # Short, unique, <=30 chars: "INV-T-" + 8 digits.
        seq = StudentInvoice.objects.count() + 1
        inv = StudentInvoice.objects.create(
            student=self.student, fee_category=self.cat, billing_period=self.period,
            description_snapshot="Tuition", category_code_snapshot="TUI",
            category_name_snapshot="Tuition",
            original_amount=Decimal(balance), net_payable=Decimal(balance),
            paid_total=Decimal("0"), balance=Decimal(balance),
            issue_date=date(2026, 3, 1), due_date=date(2026, 3, 31),
            status=StudentInvoice.Status.ISSUED, invoice_no=f"INV-T-{seq:08d}",
        )
        return inv


# --------------------------------------------------------------------------- T1..T3

class PaymentCreationTests(_Base):
    def test_t1_payment_without_invoice(self):
        before = PaymentReceipt.objects.count()
        r = payments.create_general_payment(
            student=self.student, amount=Decimal("500.00"),
            method=PaymentReceipt.Method.CASH, actor=self.clerk,
        )
        self.assertEqual(r.status, PaymentReceipt.Status.ACTIVE)
        self.assertIsNone(r.invoice_id)
        self.assertEqual(PaymentReceipt.objects.count(), before + 1)

    def test_t2_receipt_pdf_dual_copy(self):
        r = payments.create_general_payment(
            student=self.student, amount=Decimal("500.00"),
            method=PaymentReceipt.Method.CASH, actor=self.clerk,
        )
        reader = PdfReader(BytesIO(render_receipt_pdf(r)))
        self.assertEqual(len(reader.pages), 1)
        text = reader.pages[0].extract_text()
        self.assertIn("School Copy", text)
        self.assertIn("Student Copy", text)
        self.assertIn(r.number, text)

    def test_t3_idempotent_payment(self):
        key = "t3-idem"
        r1 = payments.create_general_payment(
            student=self.student, amount=Decimal("500.00"),
            method=PaymentReceipt.Method.CASH, actor=self.clerk,
            idempotency_key=key,
        )
        r2 = payments.create_general_payment(
            student=self.student, amount=Decimal("500.00"),
            method=PaymentReceipt.Method.CASH, actor=self.clerk,
            idempotency_key=key,
        )
        self.assertEqual(r1.pk, r2.pk)
        self.assertEqual(PaymentReceipt.objects.filter(idempotency_key=key).count(), 1)


# --------------------------------------------------------------------------- T4..T6

class AllocationTests(_Base):
    def _pay(self, amount="500.00", key="alloc-pay"):
        return payments.create_general_payment(
            student=self.student, amount=Decimal(amount),
            method=PaymentReceipt.Method.CASH, actor=self.clerk,
            idempotency_key=key,
        )

    def test_t4_full_allocation(self):
        inv = self._fresh_invoice("500.00")
        r = self._pay("500.00")
        a = payments.allocate_payment(
            payment=r, invoice=inv, amount=Decimal("500.00"), actor=self.acct,
            idempotency_key="alloc-full",
        )
        inv.refresh_from_db()
        self.assertEqual(a.amount, Decimal("500.00"))
        self.assertEqual(inv.balance, Decimal("0"))
        self.assertEqual(inv.status, StudentInvoice.Status.PAID)
        self.assertEqual(payments.available_credit(self.student), Decimal("0"))

    def test_t5_idempotent_allocation(self):
        inv = self._fresh_invoice("500.00")
        r = self._pay("500.00")
        a1 = payments.allocate_payment(
            payment=r, invoice=inv, amount=Decimal("500.00"), actor=self.acct,
            idempotency_key="alloc-idem",
        )
        a2 = payments.allocate_payment(
            payment=r, invoice=inv, amount=Decimal("500.00"), actor=self.acct,
            idempotency_key="alloc-idem",
        )
        self.assertEqual(a1.pk, a2.pk)

    def test_t6_idempotency_mismatch_rejected(self):
        inv = self._fresh_invoice("500.00")
        r = self._pay("500.00")
        payments.allocate_payment(
            payment=r, invoice=inv, amount=Decimal("500.00"), actor=self.acct,
            idempotency_key="alloc-mismatch",
        )
        with self.assertRaises(payments.AllocationIdempotencyMismatch):
            payments.allocate_payment(
                payment=r, invoice=inv, amount=Decimal("400.00"), actor=self.acct,
                idempotency_key="alloc-mismatch",
            )

    def test_t7_partial_then_full(self):
        inv = self._fresh_invoice("500.00")
        r = self._pay("500.00")
        payments.allocate_payment(
            payment=r, invoice=inv, amount=Decimal("300.00"), actor=self.acct,
            idempotency_key="alloc-p1",
        )
        inv.refresh_from_db()
        self.assertEqual(inv.balance, Decimal("200.00"))
        self.assertEqual(inv.status, StudentInvoice.Status.PARTIAL)
        payments.allocate_payment(
            payment=r, invoice=inv, amount=Decimal("200.00"), actor=self.acct,
            idempotency_key="alloc-p2",
        )
        inv.refresh_from_db()
        self.assertEqual(inv.balance, Decimal("0"))
        self.assertEqual(inv.status, StudentInvoice.Status.PAID)

    def test_t8_multiple_payments_to_one_invoice(self):
        inv = self._fresh_invoice("1000.00")
        r1 = self._pay("400.00", key="mp1")
        r2 = self._pay("600.00", key="mp2")
        payments.allocate_payment(payment=r1, invoice=inv, amount=Decimal("400.00"),
                                  actor=self.acct, idempotency_key="mp-a1")
        payments.allocate_payment(payment=r2, invoice=inv, amount=Decimal("600.00"),
                                  actor=self.acct, idempotency_key="mp-a2")
        inv.refresh_from_db()
        self.assertEqual(inv.balance, Decimal("0"))

    def test_t9_over_credit_rejected(self):
        inv = self._fresh_invoice("1000.00")
        r = self._pay("300.00")
        with self.assertRaises(payments.PaymentError):
            payments.allocate_payment(payment=r, invoice=inv, amount=Decimal("500.00"),
                                      actor=self.acct, idempotency_key="oc1")

    def test_t10_over_invoice_rejected(self):
        inv = self._fresh_invoice("200.00")
        r = self._pay("500.00")
        with self.assertRaises(payments.PaymentError):
            payments.allocate_payment(payment=r, invoice=inv, amount=Decimal("300.00"),
                                      actor=self.acct, idempotency_key="oi1")

    def test_t11_cross_student_rejected(self):
        other = Student.objects.create(
            full_name="Other", student_id="STU-OTHER", roll_no="2",
            class_ref=self.cls, is_active=True,
        )
        inv = self._fresh_invoice("500.00")
        inv.student = other
        inv.save(update_fields=["student"])
        r = self._pay("500.00")
        with self.assertRaises(payments.PaymentError):
            payments.allocate_payment(payment=r, invoice=inv, amount=Decimal("500.00"),
                                      actor=self.acct, idempotency_key="xs1")


# --------------------------------------------------------------------------- T-L1..T-L4 (legacy preservation)

class LegacyPreservationTests(_Base):
    def test_tl1_delta_updates_do_not_touch_history(self):
        inv = self._fresh_invoice("1000.00")
        # Simulate a legacy invoice: paid_total already set by an old receipt.
        inv.paid_total = Decimal("300.00")
        inv.balance = Decimal("700.00")
        inv.status = StudentInvoice.Status.PARTIAL
        inv.save(update_fields=["paid_total", "balance", "status"])

        r = payments.create_general_payment(
            student=self.student, amount=Decimal("500.00"),
            method=PaymentReceipt.Method.CASH, actor=self.clerk,
        )
        payments.allocate_payment(payment=r, invoice=inv, amount=Decimal("500.00"),
                                  actor=self.acct, idempotency_key="tl1")
        inv.refresh_from_db()
        self.assertEqual(inv.paid_total, Decimal("800.00"))  # 300 legacy + 500 new
        self.assertEqual(inv.balance, Decimal("200.00"))
        self.assertEqual(inv.status, StudentInvoice.Status.PARTIAL)

    def test_tl2_legacy_fully_paid_is_not_allocatable(self):
        inv = self._fresh_invoice("500.00")
        inv.paid_total = Decimal("500.00")
        inv.balance = Decimal("0")
        inv.status = StudentInvoice.Status.PAID
        inv.save(update_fields=["paid_total", "balance", "status"])
        r = payments.create_general_payment(
            student=self.student, amount=Decimal("100.00"),
            method=PaymentReceipt.Method.CASH, actor=self.clerk,
        )
        with self.assertRaises(payments.PaymentError):
            payments.allocate_payment(payment=r, invoice=inv, amount=Decimal("100.00"),
                                      actor=self.acct, idempotency_key="tl2")
        inv.refresh_from_db()
        self.assertEqual(inv.paid_total, Decimal("500.00"))
        self.assertEqual(inv.balance, Decimal("0"))


# --------------------------------------------------------------------------- T-M1..T-M4 (method mapping)

class MethodMappingTests(_Base):
    def test_tm1_each_method_maps(self):
        expected = {
            "CASH": "CASH", "BANK": "CHEQUES_CLEARING",
            "CHEQUE": "CHEQUES_CLEARING", "CARD": "CHEQUES_CLEARING",
            "BKASH": "BKASH_CLEARING", "NAGAD": "NAGAD_CLEARING",
            "ROCKET": "ROCKET_CLEARING", "OTHER": "OTHER_CLEARING",
        }
        for method, acct in expected.items():
            self.assertEqual(payments._method_debit_account(method), acct, method)


# --------------------------------------------------------------------------- T-R (receipt number uniqueness)

class ReceiptNumberTests(_Base):
    def test_tr1_numbers_are_unique(self):
        r1 = payments.create_general_payment(
            student=self.student, amount=Decimal("100.00"),
            method=PaymentReceipt.Method.CASH, actor=self.clerk,
        )
        r2 = payments.create_general_payment(
            student=self.student, amount=Decimal("100.00"),
            method=PaymentReceipt.Method.CASH, actor=self.clerk,
        )
        self.assertNotEqual(r1.number, r2.number)
        self.assertEqual(PaymentReceipt.objects.filter(number=r1.number).count(), 1)
        self.assertEqual(PaymentReceipt.objects.filter(number=r2.number).count(), 1)


# --------------------------------------------------------------------------- T-B (Bangla rendering — skip if no font)

class BanglaRenderingTests(_Base):
    def test_tb1_bangla_strings_render(self):
        font = Path(__file__).resolve().parents[2] / "static" / "fonts" / "NotoSansBengali-Regular.ttf"
        if not font.exists():
            self.skipTest("No Bangla font at static/fonts/NotoSansBengali-Regular.ttf; skipping T-B.")
        from finance import pdf as pdf_mod
        self.assertNotEqual(pdf_mod._BANGLA_FONT_NAME, "Helvetica")
        r = payments.create_general_payment(
            student=self.student, amount=Decimal("100.00"),
            method=PaymentReceipt.Method.CASH, actor=self.clerk,
        )
        reader = PdfReader(BytesIO(render_receipt_pdf(r)))
        self.assertEqual(len(reader.pages), 1)


# --------------------------------------------------------------------------- Permission grants

class PermissionGrantTests(TestCase):
    def test_accountant_has_both_new_codenames(self):
        expected = {"record_payment", "allocate_payment"}
        self.assertTrue(expected.issubset(set(GROUPS[ACCOUNTANT])))

    def test_clerk_has_record_but_not_allocate(self):
        g = GROUPS[CLERK]
        self.assertIn("record_payment", g)
        self.assertNotIn("allocate_payment", g)

    def test_auditor_has_neither(self):
        g = GROUPS[AUDITOR]
        self.assertNotIn("record_payment", g)
        self.assertNotIn("allocate_payment", g)
        
# --------------------------------------------------------------------------- unified screen

class UnifiedScreenTests(_Base):
    def test_new_invoice_url_exists(self):
        from django.urls import reverse
        self.assertTrue(reverse("finance:clerk_new_invoice"))

    def test_record_payment_url_is_removed(self):
        from django.urls import reverse, NoReverseMatch
        with self.assertRaises(NoReverseMatch):
            reverse("finance:payment_collection")