"""
PostgreSQL protections for financial tables, installed after every migrate.

* append-only: UPDATE/DELETE on ledger and audit tables raise an error
* every ledger transaction must balance (checked at COMMIT)
* finance periods may not overlap

Honest limit: whoever owns the database can drop these triggers. They stop
application bugs and ordinary users, and make tampering deliberate and visible.
All statements are idempotent.
"""
import logging

from django.db import connection

logger = logging.getLogger(__name__)

APPEND_ONLY_TABLES = [
    "finance_ledgertransaction",
    "finance_ledgerline",
    "finance_auditevent",
    "finance_invoiceadjustment",
]

FUNCTIONS_SQL = """
CREATE OR REPLACE FUNCTION finance_block_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'finance: % on % is not allowed (append-only table)', TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION finance_check_tx_balance() RETURNS trigger AS $$
DECLARE
    total_debit numeric;
    total_credit numeric;
BEGIN
    SELECT COALESCE(SUM(debit), 0), COALESCE(SUM(credit), 0)
      INTO total_debit, total_credit
      FROM finance_ledgerline WHERE tx_id = NEW.tx_id;
    IF total_debit <> total_credit THEN
        RAISE EXCEPTION 'finance: ledger transaction % is unbalanced (debit %, credit %)',
            NEW.tx_id, total_debit, total_credit
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""

PERIOD_OVERLAP_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'finance_period_no_overlap') THEN
        ALTER TABLE finance_financeperiod
            ADD CONSTRAINT finance_period_no_overlap
            EXCLUDE USING gist (daterange(start_date, end_date, '[]') WITH &&);
    END IF;
END
$$;
"""


def tables_ready():
    return "finance_ledgerline" in connection.introspection.table_names()


def install():
    """Install the protections. Returns True when installed, False when skipped."""
    if connection.vendor != "postgresql":
        logger.warning("finance: database protections skipped (not PostgreSQL).")
        return False
    if not tables_ready():
        return False
    with connection.cursor() as cursor:
        cursor.execute(FUNCTIONS_SQL)
        for table in APPEND_ONLY_TABLES:
            cursor.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
            cursor.execute(
                f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION finance_block_mutation()"
            )
        cursor.execute("DROP TRIGGER IF EXISTS finance_ledgerline_balance ON finance_ledgerline")
        cursor.execute(
            "CREATE CONSTRAINT TRIGGER finance_ledgerline_balance AFTER INSERT ON finance_ledgerline "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION finance_check_tx_balance()"
        )
        cursor.execute(PERIOD_OVERLAP_SQL)
    return True
