from django.urls import path

from . import views

app_name = "finance"

urlpatterns = [
    path("", views.home, name="home"),

    # Fee categories (custom list shows usage; create/edit come from the CRUD helper)
    path("categories/", views.category_list, name="category_list"),
    path("categories/new/", views.categories.create.as_view(), name="category_create"),
    path("categories/<int:pk>/edit/", views.categories.update.as_view(), name="category_update"),
    path("categories/<int:pk>/status/", views.category_status, name="category_status"),
    path("categories/<int:pk>/delete/", views.category_delete, name="category_delete"),
    path("invoices/new/", views.clerk_new_invoice, name="clerk_new_invoice"),
    path("invoices/<int:invoice_pk>/pay/", views.payment_receive, name="payment_receive"),
    path("receipts/<int:pk>/pdf/", views.payment_receipt_pdf, name="payment_receipt_pdf"),
    # path("payments/collect/", views.payment_collection, name="payment_collection"),
    path("allocations/", views.allocation_dashboard, name="allocation_dashboard"),
    path("allocations/<int:student_pk>/", views.allocation_form, name="allocation_form"),
    *views.student_categories.urls,

    # Fees and billing periods
    path("fee-matrix/", views.fee_matrix, name="matrix"),
    path("billing-periods/generate/", views.periods_generate, name="periods_generate"),
    *views.periods.urls,
    *views.installment_options.urls,

    # Discounts
    *views.discount_rules.urls,
    path("discount-awards/", views.award_list, name="award_list"),
    path("discount-awards/new/", views.award_create, name="award_create"),
    path("discount-awards/<int:pk>/decide/", views.award_decide, name="award_decide"),

    # Invoices
    path("invoices/", views.invoice_list, name="invoice_list"),
    path("invoices/generate/", views.invoice_generate, name="invoice_generate"),
    path("invoices/<int:pk>/", views.invoice_detail, name="invoice_detail"),
    path("invoices/<int:pk>/cancel/", views.invoice_cancel, name="invoice_cancel"),
    path("invoices/<int:pk>/adjust/", views.invoice_adjust, name="invoice_adjust"),

    # Audit trail
    path("audit/", views.audit_list, name="audit_list"),
]
