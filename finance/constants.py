"""Chart of accounts, permission codenames and role-to-group mapping."""

# system_key: (code, name, kind)
SYSTEM_ACCOUNTS = {
    # ---- Assets ----
    "CASH": ("1000", "Cash on hand", "ASSET"),
    "BKASH_CLEARING": ("1020", "bKash in clearing", "ASSET"),
    "NAGAD_CLEARING": ("1021", "Nagad in clearing", "ASSET"),
    "ROCKET_CLEARING": ("1022", "Rocket in clearing", "ASSET"),
    "OTHER_CLEARING": ("1029", "Other payments in clearing", "ASSET"),
    "CHEQUES_CLEARING": ("1150", "Cheques in clearing", "ASSET"),
    "RECEIVABLE": ("1200", "Student receivables", "ASSET"),

    # ---- Liabilities ----
    "STUDENT_CREDIT": ("2100", "Student credit (wallet)", "LIABILITY"),
    "REFUNDS_PAYABLE": ("2200", "Refunds payable", "LIABILITY"),
    "UNIDENTIFIED": ("2300", "Unidentified deposits", "LIABILITY"),
    "SALARY_PAYABLE": ("2400", "Salary payable", "LIABILITY"),

    # ---- Equity ----
    "OPENING_EQUITY": ("3000", "Opening balances equity", "EQUITY"),

    # ---- Income ----
    "FEE_INCOME": ("4000", "Fee income", "INCOME"),
    "LATE_FEE_INCOME": ("4100", "Late-fee income", "INCOME"),
    "OTHER_INCOME": ("4200", "Other income", "INCOME"),
    "DISCOUNTS": ("4900", "Discounts and scholarships", "INCOME"),
    "WAIVERS": ("4910", "Fee waivers", "INCOME"),

    # ---- Expenses ----
    "SALARY_EXPENSE": ("5100", "Salary expense", "EXPENSE"),
    "CASH_OVER_SHORT": ("5900", "Cash over/short", "EXPENSE"),
}

# (codename, human description)
PERMISSIONS = [
    ("view_finance", "Open the finance area and read invoices"),
    ("manage_feecategory", "Create, edit, archive and delete fee categories"),
    ("manage_feerule", "Set fee amounts, billing periods"),
    ("manage_discountrule", "Manage discount, scholarship and waiver rules"),
    ("award_discount", "Award discounts to students"),
    ("approve_discount", "Approve or reject discount awards"),
    ("manage_installmentoption", "Define installment options"),
    ("manage_installment_plans", "Assign installment plans to students"),
    ("manage_latefeepolicy", "Manage late-fee policies"),
    ("generate_invoice", "Generate invoices"),
    ("adjust_invoice", "Adjust invoices"),
    ("cancel_invoice", "Cancel invoices"),
    ("enter_payment", "Enter payments"),
    ("confirm_payment", "Confirm payments directly"),
    ("verify_payment", "Verify staged payments"),
    ("reject_payment", "Reject staged payments"),
    ("request_reversal", "Request a payment reversal"),
    ("reverse_payment", "Approve a payment reversal"),
    ("request_refund", "Request a refund"),
    ("approve_refund", "Approve a refund"),
    ("apply_wallet", "Apply student credit"),
    ("record_expense", "Record expenses"),
    ("approve_expense", "Approve expenses"),
    ("transfer_funds", "Transfer between accounts"),
    ("view_receipt", "View and download receipts"),
    ("reprint_receipt", "Reprint receipts"),
    ("view_reports", "View finance reports"),
    ("export_reports", "Export finance reports"),
    ("reconcile", "Reconcile accounts and statements"),
    ("close_period", "Close a finance period"),
    ("reopen_period", "Reopen a finance period"),
    ("view_audit", "View the finance audit trail"),
    ("manage_slip_register", "Maintain the bank slip register"),
    ("check_slip", "Check bank slips against the school copy"),
    ("override_slip", "Override a failed slip check"),
    ("manage_policy", "Change finance policy settings"),
    ("manage_signatures", "Manage signature images"),
    ("record_payment", "Record a payment and issue a receipt"),
    ("allocate_payment", "Allocate a payment to an invoice"),
]

ACCOUNTANT = "Finance - Accountant"
CLERK = "Finance - Clerk"
AUDITOR = "Finance - Auditor"

GROUPS = {
    ACCOUNTANT: [
        "view_finance", "generate_invoice", "adjust_invoice", "cancel_invoice", "award_discount",
        "enter_payment", "confirm_payment", "request_reversal", "request_refund",
        "apply_wallet", "record_expense", "transfer_funds", "view_receipt",
        "reprint_receipt", "view_reports", "export_reports", "reconcile",
        "manage_installment_plans",
        "record_payment", "allocate_payment",
    ],
    CLERK: ["view_finance", "enter_payment", "check_slip", "view_receipt","record_payment",],
    AUDITOR: [
        "view_finance", "verify_payment", "reject_payment", "request_reversal",
        "view_receipt", "view_reports", "export_reports", "reconcile", "view_audit",
        "approve_discount", "approve_expense",
    ],
}

ROLE_TO_GROUP = {"ACCOUNTANT": ACCOUNTANT, "CLERK": CLERK, "AUDITOR": AUDITOR}
FINANCE_ROLES = tuple(ROLE_TO_GROUP)