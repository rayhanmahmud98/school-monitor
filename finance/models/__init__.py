from .base import AppendOnlyError, AppendOnlyModel  # noqa: F401
from .billing import InvoiceAdjustment, StudentInvoice  # noqa: F401
from .catalog import (  # noqa: F401
    BillingPeriod, DiscountRule, FeeCategory, FeeRule, Frequency, FREQUENCY_FOR_KIND,
    InstallmentOption, InstallmentOptionLine, StudentCategory, StudentDiscount,
    StudentFeeProfile,
)
from .control import AuditEvent, FinancePeriod, NumberSequence  # noqa: F401
from .ledger import LedgerAccount, LedgerLine, LedgerTransaction  # noqa: F401
from .rights import FinanceRights  # noqa: F401
from .payment import PaymentAllocation, PaymentReceipt  # noqa: F401  ← added PaymentAllocation