"""Record payments, allocate them to invoices, and post the matching ledger entries."""
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from ..models import PaymentAllocation, PaymentReceipt, StudentInvoice
from . import audit, ledger


class PaymentError(Exception):
    """Raised when a payment cannot be recorded or allocated."""


# ---- account mapping --------------------------------------------------------------------

_METHOD_ACCOUNT = {
    PaymentReceipt.Method.CASH: "CASH",
    PaymentReceipt.Method.BANK_TRANSFER: "CHEQUES_CLEARING",
    PaymentReceipt.Method.CHEQUE: "CHEQUES_CLEARING",
    PaymentReceipt.Method.CARD: "CHEQUES_CLEARING",
    PaymentReceipt.Method.BKASH: "BKASH_CLEARING",
    PaymentReceipt.Method.NAGAD: "NAGAD_CLEARING",
    PaymentReceipt.Method.ROCKET: "ROCKET_CLEARING",
    PaymentReceipt.Method.OTHER: "OTHER_CLEARING",
}


def _method_debit_account(method: str) -> str:
    """Return the ledger account key to debit for a payment of this method."""
    try:
        return _METHOD_ACCOUNT[method]
    except KeyError:
        raise PaymentError(f"Unsupported payment method: {method}")


# ---- student credit (computed, not stored) ---------------------------------------------

def available_credit(student) -> Decimal:
    """Total ACTIVE payments minus the sum of their allocations."""
    from django.db.models import Sum

    paid = (
        PaymentReceipt.objects
        .filter(student=student, status=PaymentReceipt.Status.ACTIVE)
        .aggregate(t=Sum("amount"))["t"] or Decimal("0")
    )
    allocated = (
        PaymentAllocation.objects
        .filter(payment__student=student)
        .aggregate(t=Sum("amount"))["t"] or Decimal("0")
    )
    return paid - allocated


# ---- new flow: create a payment without an invoice ------------------------------------

MAX_RECEIPT_ATTEMPTS = 5


def _next_receipt_number() -> str:
    """Compute the next RCPT-YYYY-NNNNNN for the current year.

    Concurrency safety is provided by the unique constraint on PaymentReceipt.number
    plus the caller's retry loop. This function has no side effects.
    """
    year = timezone.localdate().year
    prefix = f"RCPT-{year}-"
    last = (
        PaymentReceipt.objects
        .filter(number__startswith=prefix)
        .order_by("-number")
        .first()
    )
    n = 1
    if last:
        try:
            n = int(last.number.rsplit("-", 1)[1]) + 1
        except (ValueError, IndexError):
            n = 1
    return f"{prefix}{n:06d}"


def create_general_payment(
    *,
    student,
    amount: Decimal,
    method: str,
    actor,
    payment_date=None,
    reference: str = "",
    reference_type: str = PaymentReceipt.ReferenceType.NONE,
    cheque_date=None,
    bank_name: str = "",
    branch_name: str = "",
    note: str = "",
    idempotency_key: str = None,
) -> PaymentReceipt:
    """Record a payment without an invoice. Posts Dr <method account> / Cr STUDENT_CREDIT.

    Idempotency:
      - If idempotency_key is provided and a receipt with that key already exists,
        the existing receipt is returned unchanged (no second ledger posting, no
        second audit event).
      - If idempotency_key is not provided, the caller accepts duplicate-request risk.
    """
    if amount is None or amount <= 0:
        raise PaymentError("Payment amount must be positive.")

    # Idempotency fast path: existing receipt with this key is returned as-is.
    if idempotency_key:
        existing = PaymentReceipt.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing

    debit_key = _method_debit_account(method)
    paid_on = payment_date or timezone.localdate()

    for attempt in range(MAX_RECEIPT_ATTEMPTS):
        try:
            with transaction.atomic():
                receipt = PaymentReceipt(
                    number=_next_receipt_number(),
                    student=student,
                    invoice=None,
                    amount=amount,
                    method=method,
                    reference=reference or "",
                    reference_type=reference_type or PaymentReceipt.ReferenceType.NONE,
                    cheque_date=cheque_date,
                    bank_name=bank_name or "",
                    branch_name=branch_name or "",
                    note=note or "",
                    payment_date=paid_on,
                    received_by=actor,
                    received_at=timezone.now(),
                    status=PaymentReceipt.Status.ACTIVE,
                    idempotency_key=idempotency_key or None,
                )
                receipt.save()

                tx = ledger.post(
                    tx_type="payment",
                    posting_date=paid_on,
                    description=f"Payment {receipt.number} from {student.full_name}",
                    lines=[
                        {"account": debit_key, "debit": amount, "student": student},
                        {"account": "STUDENT_CREDIT", "credit": amount, "student": student},
                    ],
                    actor=actor,
                    source=("payment", receipt.pk),
                )
                receipt.ledger_transaction = tx
                receipt.save(update_fields=["ledger_transaction"])

                audit.record(
                    actor=actor,
                    event_type="payment.received",
                    obj=receipt,
                    new={
                        "student": student.full_name,
                        "amount": str(amount),
                        "method": method,
                        "reference": reference or "",
                    },
                )
                return receipt

        except IntegrityError as exc:
            # Only retry on receipt-number collision. Any other integrity error
            # (e.g. idempotency_key conflict from a concurrent caller) is a real
            # error and is re-raised.
            if "number" in str(exc).lower() and attempt < MAX_RECEIPT_ATTEMPTS - 1:
                continue
            raise

    raise PaymentError("Could not allocate a receipt number. Please try again.")


# ---- new flow: allocate a payment to an invoice ---------------------------------------

def _apply_allocation(invoice: StudentInvoice, amount: Decimal) -> None:
    """Apply a delta to an invoice's paid_total/balance/status. Does not save."""
    invoice.paid_total = (invoice.paid_total or Decimal("0")) + amount
    invoice.balance = invoice.net_payable - invoice.paid_total
    if invoice.balance <= 0:
        invoice.balance = Decimal("0")
        invoice.status = StudentInvoice.Status.PAID
    else:
        invoice.status = StudentInvoice.Status.PARTIAL


def allocate_payment(
    *,
    payment: PaymentReceipt,
    invoice: StudentInvoice,
    amount: Decimal,
    actor,
    idempotency_key: str = None,
) -> PaymentAllocation:
    """Link a payment to an invoice. Posts Dr STUDENT_CREDIT / Cr RECEIVABLE.

    Idempotency:
      - If idempotency_key is provided and an allocation with that key already exists,
        the existing allocation is returned ONLY IF it matches (payment, invoice, amount).
        Otherwise AllocationIdempotencyMismatch is raised.
      - Same-key + matching -> no second ledger posting, no second audit event.
      - Same-key + different fields -> rejected with a clear error.
    """
    if amount is None or amount <= 0:
        raise PaymentError("Allocation amount must be positive.")

    if payment.student_id != invoice.student_id:
        raise PaymentError("Payment and invoice belong to different students.")

    if payment.status != PaymentReceipt.Status.ACTIVE:
        raise PaymentError(f"Cannot allocate a {payment.status} payment.")

    # Idempotency fast path.
    if idempotency_key:
        existing = PaymentAllocation.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            if (existing.payment_id == payment.pk
                    and existing.invoice_id == invoice.pk
                    and existing.amount == amount):
                return existing
            raise AllocationIdempotencyMismatch(
                "A different allocation already exists with this idempotency key. "
                "Use a fresh key for a new allocation."
            )

    with transaction.atomic():
        # Row locks: prevent concurrent over-allocation.
        locked_payment = PaymentReceipt.objects.select_for_update().get(pk=payment.pk)
        locked_invoice = StudentInvoice.objects.select_for_update().get(pk=invoice.pk)

        credit = available_credit(locked_payment.student)
        if amount > credit:
            raise PaymentError(
                f"Amount {amount} exceeds available credit {credit}."
            )
        if amount > locked_invoice.balance:
            raise PaymentError(
                f"Amount {amount} exceeds invoice balance {locked_invoice.balance}."
            )

        try:
            allocation = PaymentAllocation.objects.create(
                payment=locked_payment,
                invoice=locked_invoice,
                amount=amount,
                allocated_by=actor,
                allocated_at=timezone.now(),
                idempotency_key=idempotency_key or None,
            )
        except IntegrityError:
            # Same key raced with another request; re-read and validate.
            if idempotency_key:
                existing = PaymentAllocation.objects.filter(idempotency_key=idempotency_key).first()
                if (existing
                        and existing.payment_id == locked_payment.pk
                        and existing.invoice_id == locked_invoice.pk
                        and existing.amount == amount):
                    return existing
            raise

        tx = ledger.post(
            tx_type="allocation",
            posting_date=timezone.localdate(),
            description=f"Allocate {allocation.amount} from {locked_payment.number} "
                        f"to {locked_invoice.invoice_no}",
            lines=[
                {"account": "STUDENT_CREDIT", "debit": amount,
                 "student": locked_payment.student},
                {"account": "RECEIVABLE", "credit": amount,
                 "student": locked_payment.student, "fee_category": locked_invoice.fee_category},
            ],
            actor=actor,
            source=("allocation", allocation.pk),
        )

        _apply_allocation(locked_invoice, amount)
        locked_invoice.save(update_fields=["paid_total", "balance", "status"])

        audit.record(
            actor=actor,
            event_type="payment.allocated",
            obj=allocation,
            new={
                "payment": locked_payment.number,
                "invoice": locked_invoice.invoice_no,
                "amount": str(amount),
            },
        )
        return allocation


class AllocationIdempotencyMismatch(PaymentError):
    """Raised when an idempotency key is reused with different allocation fields."""


# ---- legacy flow: preserved for backward compatibility --------------------------------

def _cash_account(method: str) -> str:
    """Legacy helper. The new flow uses _method_debit_account instead."""
    return "CHEQUES_CLEARING"


@transaction.atomic
def record_payment(
    *,
    invoice: StudentInvoice,
    amount: Decimal,
    method: str,
    actor,
    reference: str = "",
    note: str = "",
    auto_approve: bool = False,
) -> PaymentReceipt:
    """Legacy: record a payment against an existing invoice. Kept for the
    payment_receive view. New payments go through create_general_payment."""
    if amount <= 0:
        raise PaymentError("Payment amount must be positive.")

    if amount > invoice.balance:
        raise PaymentError(
            f"Amount {amount} exceeds outstanding balance {invoice.balance}."
        )

    receipt = PaymentReceipt.objects.create(
        invoice=invoice,
        student=invoice.student,
        amount=amount,
        method=method,
        reference=reference,
        note=note,
        received_by=actor,
        received_at=timezone.now(),
        payment_date=timezone.localdate(),
        status=(
            PaymentReceipt.Status.APPROVED
            if auto_approve else PaymentReceipt.Status.PENDING
        ),
        approved_by=actor if auto_approve else None,
        approved_at=timezone.now() if auto_approve else None,
    )

    if auto_approve:
        _post_and_attach(receipt)

    audit.record(
        actor=actor,
        event_type="payment.received" if auto_approve else "payment.pending",
        obj=receipt,
        new={
            "invoice": invoice.invoice_no,
            "student": invoice.student.full_name,
            "amount": str(amount),
            "method": method,
            "reference": reference,
        },
        reason=note,
    )

    return receipt


def approve_payment(receipt: PaymentReceipt, actor) -> PaymentReceipt:
    if receipt.status != PaymentReceipt.Status.PENDING:
        raise PaymentError(f"Cannot approve a {receipt.status} payment.")

    receipt.status = PaymentReceipt.Status.APPROVED
    receipt.approved_by = actor
    receipt.approved_at = timezone.now()
    receipt.save()

    _post_and_attach(receipt)

    audit.record(actor=actor, event_type="payment.approved", obj=receipt)
    return receipt


def reject_payment(receipt: PaymentReceipt, actor, reason: str) -> PaymentReceipt:
    if receipt.status != PaymentReceipt.Status.PENDING:
        raise PaymentError(f"Cannot reject a {receipt.status} payment.")
    if not reason:
        raise PaymentError("A reason is required to reject a payment.")

    receipt.status = PaymentReceipt.Status.REJECTED
    receipt.approved_by = actor
    receipt.approved_at = timezone.now()
    receipt.rejection_reason = reason
    receipt.save()

    audit.record(actor=actor, event_type="payment.rejected", obj=receipt, reason=reason)
    return receipt


def _post_and_attach(receipt: PaymentReceipt):
    """Legacy: post Dr <method account> / Cr RECEIVABLE and apply the payment
    to the linked invoice. Only used by record_payment/approve_payment."""
    debit_key = _method_debit_account(receipt.method)
    tx = ledger.post(
        tx_type="payment",
        posting_date=receipt.payment_date or timezone.localdate(),
        description=f"Payment {receipt.number} for invoice {receipt.invoice.invoice_no}",
        lines=[
            {"account": debit_key, "debit": receipt.amount, "student": receipt.student},
            {"account": "RECEIVABLE", "credit": receipt.amount, "student": receipt.student},
        ],
        actor=receipt.received_by,
        source=("payment", receipt.pk),
    )
    receipt.ledger_transaction = tx
    receipt.save(update_fields=["ledger_transaction"])

    invoice = receipt.invoice
    invoice.paid_total = invoice.paid_total + receipt.amount
    invoice.balance = invoice.balance - receipt.amount
    if invoice.balance <= 0:
        invoice.balance = 0
        invoice.status = StudentInvoice.Status.PAID
    invoice.save(update_fields=["paid_total", "balance", "status"])