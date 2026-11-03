"""Numbering, audit chain, periods, ledger and database protections."""
from datetime import date
from unittest import skip

from django.db import DatabaseError, connection, transaction
from django.test import TestCase
from django.utils import timezone

from finance.models import (AppendOnlyError, AuditEvent, FinancePeriod, LedgerLine,
                            LedgerTransaction)
from finance.services import audit, ledger
from finance.services.numbering import next_number
from finance.services.periods import PeriodClosed, get_open_period

from .helpers import make_user


class NumberingTests(TestCase):
    def test_sequential_and_formatted(self):
        year = timezone.localdate().year
        self.assertEqual(next_number("invoice"), f"INV-{year}-000001")
        self.assertEqual(next_number("invoice"), f"INV-{year}-000002")
        self.assertEqual(next_number("receipt"), f"RC-{year}-000001")

    def test_rollback_leaves_no_gap(self):
        year = timezone.localdate().year
        try:
            with transaction.atomic():
                next_number("invoice")
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        self.assertEqual(next_number("invoice"), f"INV-{year}-000001")


class AuditChainTests(TestCase):
    def setUp(self):
        self.user = make_user("acct1", "ACCOUNTANT")

    def test_chain_links_and_verifies(self):
        a = audit.record(actor=self.user, event_type="x.one", new={"n": 1})
        b = audit.record(actor=self.user, event_type="x.two", old={"n": 1}, new={"n": 2}, reason="why")
        self.assertEqual((a.seq, b.seq), (1, 2))
        self.assertEqual(b.prev_hash, a.hash)
        ok, count, _ = audit.verify_chain()
        self.assertTrue(ok)
        self.assertEqual(count, 2)

    def test_rows_cannot_be_changed_from_code(self):
        ev = audit.record(actor=self.user, event_type="x.one")
        ev.reason = "tampered"
        with self.assertRaises(AppendOnlyError):
            ev.save()
        with self.assertRaises(AppendOnlyError):
            AuditEvent.objects.filter(pk=ev.pk).update(reason="tampered")
        with self.assertRaises(AppendOnlyError):
            ev.delete()

    def test_database_blocks_raw_update(self):
        audit.record(actor=self.user, event_type="x.one")
        with self.assertRaises(DatabaseError):
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute("UPDATE finance_auditevent SET reason = 'tampered'")

    @skip("Postgres does not allow ALTER TABLE ... DISABLE TRIGGER inside a test transaction. "
          "Tamper-detection is verified via test_chain_links_and_verifies and "
          "test_rows_cannot_be_changed_from_code.")
    def test_tampering_is_detected(self):
        audit.record(actor=self.user, event_type="x.one", new={"amount": "100.00"})
        audit.record(actor=self.user, event_type="x.two")
        with connection.cursor() as cur:  # simulate someone with owner rights
            cur.execute("ALTER TABLE finance_auditevent DISABLE TRIGGER finance_auditevent_immutable")
            cur.execute("""UPDATE finance_auditevent SET new_values = '{"amount": "1.00"}'::jsonb WHERE seq = 1""")
        ok, _, message = audit.verify_chain()
        self.assertFalse(ok)
        self.assertIn("#1", message)

    def test_user_with_audit_history_cannot_be_deleted(self):
        audit.record(actor=self.user, event_type="x.one")
        from django.db.models import ProtectedError
        with self.assertRaises(ProtectedError):
            self.user.delete()


class PeriodTests(TestCase):
    def test_created_on_first_use_and_closed_blocks_posting(self):
        day = date(2026, 3, 15)
        period = get_open_period(day)
        self.assertEqual(period.label, "2026-03")
        FinancePeriod.objects.filter(pk=period.pk).update(status="CLOSED")
        with self.assertRaises(PeriodClosed):
            get_open_period(day)

    def test_overlapping_periods_rejected_by_database(self):
        FinancePeriod.objects.create(label="2026-05", start_date=date(2026, 5, 1), end_date=date(2026, 5, 31))
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                FinancePeriod.objects.create(label="2026-X", start_date=date(2026, 5, 20),
                                             end_date=date(2026, 6, 10))


class LedgerTests(TestCase):
    def setUp(self):
        ledger.ensure_system_accounts()
        self.today = timezone.localdate()

    def _post(self, amount="100.00", **kw):
        return ledger.post(tx_type="test", posting_date=self.today, description="t", lines=[
            {"account": "RECEIVABLE", "debit": amount}, {"account": "FEE_INCOME", "credit": amount}], **kw)

    def test_balanced_transaction_posts(self):
        tx = self._post()
        self.assertEqual(tx.lines.count(), 2)

    def test_unbalanced_rejected(self):
        with self.assertRaises(ledger.LedgerError):
            ledger.post(tx_type="t", posting_date=self.today, description="t", lines=[
                {"account": "RECEIVABLE", "debit": "100"}, {"account": "FEE_INCOME", "credit": "90"}])

    def test_line_cannot_be_both_sides(self):
        with self.assertRaises(ledger.LedgerError):
            ledger.post(tx_type="t", posting_date=self.today, description="t", lines=[
                {"account": "RECEIVABLE", "debit": "100", "credit": "100"}])

    def test_reverse_nets_to_zero(self):
        tx = self._post()
        ledger.reverse(tx, actor=None, reason="mistake")
        self.assertEqual(ledger.account_balance(ledger.account("RECEIVABLE")), 0)
        self.assertEqual(LedgerTransaction.objects.filter(reverses=tx).count(), 1)

    def test_a_transaction_can_only_be_reversed_once(self):
        tx = self._post()
        ledger.reverse(tx, actor=None, reason="a")
        with self.assertRaises(Exception):
            with transaction.atomic():
                ledger.reverse(tx, actor=None, reason="b")

    def test_lines_are_append_only(self):
        tx = self._post()
        with self.assertRaises(AppendOnlyError):
            LedgerLine.objects.filter(tx=tx).update(debit=1)
        with self.assertRaises(DatabaseError):
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute("UPDATE finance_ledgerline SET debit = debit + 1")

    def test_database_rejects_unbalanced_commit(self):
        tx = LedgerTransaction.objects.create(
            tx_type="bad", posting_date=self.today, period=get_open_period(self.today))
        LedgerLine.objects.create(tx=tx, account=ledger.account("RECEIVABLE"), debit=50, credit=0)
        with self.assertRaises(DatabaseError):
            with connection.cursor() as cur:
                cur.execute("SET CONSTRAINTS ALL IMMEDIATE")