"""Finance views. Thin: validation and money logic live in finance.services."""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from academics.models import AcademicYear
from accounts.utils import paginate
from students.models import Student

from .crud import build_finance_crud
from .forms import (
    AdjustmentForm, BillingPeriodForm, BulkGenerateForm, CancelForm,
    ClerkNewInvoiceForm, DiscountRuleForm, FeeCategoryForm,
    InstallmentOptionForm, MonthlyPeriodsForm, PaymentReceiptForm,
    StudentCategoryForm, StudentDiscountForm,
)
from .models import (
    AuditEvent, BillingPeriod, DiscountRule, FeeCategory, InstallmentOption,
    LedgerTransaction, PaymentReceipt, StudentCategory, StudentDiscount,
    StudentInvoice,
)
from .permissions import finance_permission_required
from .services import audit, fees, invoicing, payments
from .services.periods import PeriodClosed, create_monthly_periods, month_bounds


# ---- configuration CRUD ------------------------------------------------------------
categories = build_finance_crud(
    name="category", slug="categories", model_class=FeeCategory, form_cls=FeeCategoryForm,
    title="Fee categories", singular="Fee category", permission="manage_feecategory",
    event_prefix="feecategory", allow_delete=False,
    columns=[("Code", "code"), ("Name", "name"), ("Status", "get_status_display")])

student_categories = build_finance_crud(
    name="studentcategory", slug="student-categories", model_class=StudentCategory,
    form_cls=StudentCategoryForm, title="Student categories", singular="Student category",
    permission="manage_feecategory", event_prefix="studentcategory",
    columns=[("Code", "code"), ("Name", "name"), ("Active", "is_active")],
    search_fields=("code", "name"))

periods = build_finance_crud(
    name="period", slug="billing-periods", model_class=BillingPeriod, form_cls=BillingPeriodForm,
    title="Billing periods", singular="Billing period", permission="manage_feerule",
    event_prefix="billingperiod", select_related=("academic_year",),
    columns=[("Year", "academic_year"), ("Kind", "get_kind_display"), ("Label", "label"),
             ("Issue", "issue_date"), ("Due", "due_date")],
    search_fields=("label", "academic_year__name"), ordering=("-start_date", "label"),
    can_delete=lambda obj, request: not obj.invoices.exists())

installment_options = build_finance_crud(
    name="installmentoption", slug="installment-options", model_class=InstallmentOption,
    form_cls=InstallmentOptionForm, title="Installment options", singular="Installment option",
    permission="manage_installmentoption", event_prefix="installmentoption",
    columns=[("Name", "name"), ("Installments", "installments"), ("Interval", "get_interval_display"),
             ("Split", "get_split_display"), ("Active", "is_active")],
    search_fields=("name",))

discount_rules = build_finance_crud(
    name="discountrule", slug="discount-rules", model_class=DiscountRule, form_cls=DiscountRuleForm,
    title="Discount rules", singular="Discount rule", permission="manage_discountrule",
    event_prefix="discountrule",
    columns=[("Name", "name"), ("Kind", "get_kind_display"), ("Type", "get_value_type_display"),
             ("Value", "value"), ("Priority", "priority"), ("Active", "is_active")],
    search_fields=("name",),
    can_delete=lambda obj, request: not obj.awards.exists() and not obj.adjustments.exists())


def _parse_date(value, default=None):
    try:
        return date.fromisoformat(value) if value else default
    except ValueError:
        return default


# ---- home ------------------------------------------------------------------------------
@finance_permission_required("view_finance")
def home(request):
    today = timezone.localdate()
    live = StudentInvoice.objects.exclude(status=StudentInvoice.Status.CANCELLED)
    open_inv = live.filter(balance__gt=0)
    first, last = month_bounds(today)
    overdue = open_inv.filter(due_date__lt=today)
    ctx = {
        "issued_this_month": live.filter(issue_date__range=(first, last)).count(),
        "outstanding": open_inv.aggregate(t=Sum("balance"))["t"] or 0,
        "open_count": open_inv.count(),
        "overdue_total": overdue.aggregate(t=Sum("balance"))["t"] or 0,
        "overdue_count": overdue.count(),
        "category_count": FeeCategory.objects.filter(status=FeeCategory.Status.ACTIVE).count(),
        "pending_awards": StudentDiscount.objects.filter(
            approval_status=StudentDiscount.Approval.PENDING).count(),
        "recent_events": AuditEvent.objects.select_related("actor")[:8],
    }
    return render(request, "finance/home.html", ctx)


# ---- fee categories ----------------------------------------------------------------------
@finance_permission_required("manage_feecategory")
def category_list(request):
    rows = []
    for category in FeeCategory.objects.all():
        usage = fees.category_usage(category)
        rows.append({"category": category, "usage": usage, "total": sum(usage.values())})
    return render(request, "finance/category_list.html", {"rows": rows})


@finance_permission_required("manage_feecategory")
def category_status(request, pk):
    category = get_object_or_404(FeeCategory, pk=pk)
    new_status = request.POST.get("status")
    if request.method == "POST" and new_status in FeeCategory.Status.values:
        fees.set_category_status(category, new_status, request.user, request)
        messages.success(request, f"{category.name} is now {category.get_status_display().lower()}.")
    return redirect("finance:category_list")


@finance_permission_required("manage_feecategory")
def category_delete(request, pk):
    category = get_object_or_404(FeeCategory, pk=pk)
    usage = fees.category_usage(category)
    deletable = sum(usage.values()) == 0
    if request.method == "POST":
        try:
            fees.delete_category(category, request.user, request)
        except fees.FeeError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Fee category deleted.")
            return redirect("finance:category_list")
    return render(request, "finance/category_delete.html",
                  {"category": category, "usage": usage, "deletable": deletable})


# ---- fee amount matrix ---------------------------------------------------------------------
@finance_permission_required("manage_feerule")
def fee_matrix(request):
    data = request.POST if request.method == "POST" else request.GET
    years = list(AcademicYear.objects.all())
    year = None
    if data.get("year", "").isdigit():
        year = next((y for y in years if y.pk == int(data["year"])), None)
    year = year or next((y for y in years if y.is_current), None) or (years[0] if years else None)
    if year is None:
        return render(request, "finance/matrix.html", {"years": years, "year": None})

    today = timezone.localdate()
    effective = _parse_date(data.get("effective_from"), today)
    cats, classes, cells = fees.matrix_data(year, effective)
    proposed, notice = {}, ""

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "preview_increase":
            try:
                percent = Decimal(request.POST.get("percent", "").strip())
            except InvalidOperation:
                messages.error(request, "Enter the percentage increase as a number.")
            else:
                for key, rule in cells.items():
                    proposed[key] = fees.increase(rule.amount, percent)
                notice = (f"Preview: amounts raised by {percent}%. Nothing is saved until you press "
                          "Save changes.")
        elif action == "copy_prev":
            source = next((y for y in years if str(y.pk) == request.POST.get("from_year")), None)
            if source is None:
                messages.error(request, "Choose the year to copy from.")
            else:
                s_cats, s_classes, s_cells = fees.matrix_data(source, effective)
                by_name = {(c.name, c.section): c for c in classes}
                for (cat_id, cls_id), rule in s_cells.items():
                    src_cls = next((c for c in s_classes if c.pk == cls_id), None)
                    target = by_name.get((src_cls.name, src_cls.section)) if src_cls else None
                    if target:
                        proposed[(cat_id, target.pk)] = rule.amount
                notice = f"Preview: amounts copied from {source}. Press Save changes to apply them."
        elif action == "save":
            saved, errors = 0, []
            with transaction.atomic():
                for cat in cats:
                    for cls in classes:
                        raw = request.POST.get(f"amt_{cat.pk}_{cls.pk}", "").strip()
                        if raw == "":
                            continue
                        try:
                            result = fees.set_amount(cat, year, cls, Decimal(raw), effective,
                                                     request.user, request)
                        except (InvalidOperation, fees.FeeError) as exc:
                            errors.append(f"{cat.name} / {cls}: {exc if isinstance(exc, fees.FeeError) else 'not a number'}")
                            continue
                        saved += 1 if result else 0
            for err in errors:
                messages.error(request, err)
            if saved:
                messages.success(request, f"{saved} fee amount(s) saved (effective {effective}).")
            elif not errors:
                messages.info(request, "No amounts changed.")
            return redirect(f"{request.path}?year={year.pk}&effective_from={effective}")

    rows = []
    for cat in cats:
        row = []
        for cls in classes:
            rule = cells.get((cat.pk, cls.pk))
            value = proposed.get((cat.pk, cls.pk), rule.amount if rule else "")
            row.append({"cls": cls, "name": f"amt_{cat.pk}_{cls.pk}", "current": rule.amount if rule else None,
                        "value": value, "changed": (cat.pk, cls.pk) in proposed
                        and (rule is None or proposed[(cat.pk, cls.pk)] != rule.amount)})
        rows.append({"category": cat, "cells": row})
    return render(request, "finance/matrix.html", {
        "years": years, "year": year, "classes": classes, "rows": rows,
        "effective": effective, "notice": notice,
        "other_years": [y for y in years if y.pk != year.pk]})


# ---- billing periods ------------------------------------------------------------------------
@finance_permission_required("manage_feerule")
def periods_generate(request):
    form = MonthlyPeriodsForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        year = form.cleaned_data["academic_year"]
        created = create_monthly_periods(year, form.cleaned_data["issue_day"],
                                         form.cleaned_data["due_day"])
        audit.record(actor=request.user, event_type="billingperiod.monthly_generated",
                     object_type="AcademicYear", object_id=str(year.pk),
                     new={"year": str(year), "created": created}, request=request)
        messages.success(request, f"{created} monthly billing period(s) created for {year}.")
        return redirect("finance:period_list")
    return render(request, "crud/form.html", {
        "form": form, "title": "Generate monthly billing periods",
        "cancel_url": "/finance/billing-periods/"})


# ---- discount awards -------------------------------------------------------------------------
@finance_permission_required("award_discount")
def award_list(request):
    qs = StudentDiscount.objects.select_related("student", "student__class_ref", "rule",
                                                "awarded_by", "approved_by")
    status = request.GET.get("status", "")
    if status in StudentDiscount.Approval.values:
        qs = qs.filter(approval_status=status)
    page_obj, querystring = paginate(request, qs, 20)
    return render(request, "finance/award_list.html", {
        "page_obj": page_obj, "qs": querystring, "status": status,
        "statuses": StudentDiscount.Approval.choices})


@finance_permission_required("award_discount")
def award_create(request):
    form = StudentDiscountForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            award = form.save()
            audit.record(actor=request.user, event_type="discount.awarded", obj=award,
                         new=audit.snapshot(award), request=request)
        messages.success(request, "Discount awarded." if award.approval_status == "APPROVED"
                         else "Discount awarded and waiting for approval.")
        return redirect("finance:award_list")
    return render(request, "crud/form.html", {
        "form": form, "title": "Award a discount", "cancel_url": "/finance/discount-awards/"})


@finance_permission_required("approve_discount")
def award_decide(request, pk):
    award = get_object_or_404(StudentDiscount, pk=pk)
    decision = request.POST.get("decision")
    if request.method != "POST" or decision not in ("APPROVED", "REJECTED"):
        return redirect("finance:award_list")
    if award.approval_status != StudentDiscount.Approval.PENDING:
        messages.warning(request, "This award has already been decided.")
    elif award.awarded_by_id == request.user.pk:
        messages.error(request, "You cannot approve a discount you awarded yourself.")
    else:
        with transaction.atomic():
            old = award.approval_status
            award.approval_status, award.approved_by = decision, request.user
            award.save(update_fields=["approval_status", "approved_by"])
            audit.record(actor=request.user, event_type=f"discount.{decision.lower()}", obj=award,
                         old={"approval_status": old}, new={"approval_status": decision},
                         request=request)
        messages.success(request, f"Award {decision.lower()}.")
    return redirect("finance:award_list")


# ---- invoices -----------------------------------------------------------------------------------
@finance_permission_required("view_finance")
def invoice_list(request):
    qs = StudentInvoice.objects.select_related("student", "student__class_ref", "fee_category",
                                               "billing_period")
    f = {k: request.GET.get(k, "").strip() for k in ("q", "status", "category", "period", "overdue")}
    if f["q"]:
        qs = qs.filter(Q(invoice_no__icontains=f["q"]) | Q(student__full_name__icontains=f["q"])
                       | Q(student__student_id__icontains=f["q"]))
    if f["status"] in StudentInvoice.Status.values:
        qs = qs.filter(status=f["status"])
    if f["category"].isdigit():
        qs = qs.filter(fee_category_id=f["category"])
    if f["period"].isdigit():
        qs = qs.filter(billing_period_id=f["period"])
    if f["overdue"] == "1":
        qs = qs.filter(status__in=["ISSUED", "PARTIAL"], balance__gt=0,
                       due_date__lt=timezone.localdate())
    totals = qs.aggregate(net=Sum("net_payable"), paid=Sum("paid_total"), balance=Sum("balance"),
                          n=Count("id"))
    page_obj, querystring = paginate(request, qs, 25)
    return render(request, "finance/invoice_list.html", {
        "page_obj": page_obj, "qs": querystring, "f": f, "totals": totals,
        "statuses": StudentInvoice.Status.choices,
        "categories": FeeCategory.objects.all(),
        "periods": BillingPeriod.objects.select_related("academic_year")})


@finance_permission_required("view_finance")
def invoice_detail(request, pk):
    invoice = get_object_or_404(
        StudentInvoice.objects.select_related("student", "student__class_ref", "fee_category",
                                              "billing_period", "issued_by"), pk=pk)
    txs = (LedgerTransaction.objects.filter(source_type="invoice", source_id=invoice.pk)
           .prefetch_related("lines__account").order_by("id"))
    return render(request, "finance/invoice_detail.html", {
        "invoice": invoice, "adjustments": invoice.adjustments.select_related("discount_rule"),
        "txs": txs})


@finance_permission_required("view_finance")
def invoice_generate(request):
    form = BulkGenerateForm(request.POST or None)
    preview = result = None
    if request.method == "POST" and form.is_valid():
        period, cls = form.cleaned_data["period"], form.cleaned_data["class_ref"]
        if request.POST.get("action") == "run":
            try:
                result = invoicing.generate_bulk(period, request.user, class_ref=cls, request=request)
            except (invoicing.InvoiceError, PeriodClosed) as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, f"{len(result.created)} invoice(s) created, "
                                          f"{result.skipped} already existed.")
        else:
            preview = invoicing.preview_bulk(period, class_ref=cls)
    return render(request, "finance/invoice_generate.html",
                  {"form": form, "preview": preview, "result": result})


@finance_permission_required("cancel_invoice")
def invoice_cancel(request, pk):
    invoice = get_object_or_404(StudentInvoice, pk=pk)
    form = CancelForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            invoicing.cancel_invoice(invoice.pk, form.cleaned_data["reason"], request.user, request)
        except (invoicing.InvoiceError, PeriodClosed) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"{invoice.invoice_no} cancelled.")
            return redirect("finance:invoice_detail", pk=invoice.pk)
    return render(request, "crud/form.html", {
        "form": form, "title": f"Cancel invoice {invoice.invoice_no}",
        "cancel_url": f"/finance/invoices/{invoice.pk}/"})


@finance_permission_required("adjust_invoice")
def invoice_adjust(request, pk):
    invoice = get_object_or_404(StudentInvoice, pk=pk)
    form = AdjustmentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            invoicing.add_adjustment(invoice.pk, form.cleaned_data["choice"], form.cleaned_data["amount"],
                                     form.cleaned_data["reason"], request.user, request)
        except (invoicing.InvoiceError, PeriodClosed) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Adjustment recorded.")
            return redirect("finance:invoice_detail", pk=invoice.pk)
    return render(request, "crud/form.html", {
        "form": form, "title": f"Adjust invoice {invoice.invoice_no}",
        "cancel_url": f"/finance/invoices/{invoice.pk}/"})


@finance_permission_required("view_audit")
def audit_list(request):
    if request.method == "POST":
        ok, count, message = audit.verify_chain()
        (messages.success if ok else messages.error)(request, message)
        return redirect("finance:audit_list")
    qs = AuditEvent.objects.select_related("actor")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(event_type__icontains=q) | Q(object_type__icontains=q)
                       | Q(reason__icontains=q) | Q(actor_label__icontains=q))
    page_obj, querystring = paginate(request, qs, 30)
    return render(request, "finance/audit_list.html", {"page_obj": page_obj, "qs": querystring, "q": q})


# ---- unified new invoice / receive payment ------------------------------------------------

@finance_permission_required("view_finance")
def clerk_new_invoice(request):
    """
    Unified payment entry. Depending on form.mode:
      - invoice: create one invoice per selected category, then record a payment.
      - credit:  record a payment without creating an invoice (student credit).
    """
    if request.method == "POST":
        form = ClerkNewInvoiceForm(request.POST)
        if form.is_valid():
            student = form.cleaned_data["student"]
            amount = form.cleaned_data["amount_paid"]
            method = form.cleaned_data["method"]
            mode = form.cleaned_data["mode"]
            
            payment_kwargs = dict(
                student=student,
                amount=amount,
                method=method,
                actor=request.user,
                payment_date=timezone.localdate(),
                reference=form.cleaned_data.get("reference") or "",
                reference_type=form.cleaned_data.get("reference_type") or "NONE",
                cheque_date=form.cleaned_data.get("cheque_date"),
                bank_name=form.cleaned_data.get("bank_name") or "",
                branch_name=form.cleaned_data.get("branch_name") or "",
                note=form.cleaned_data.get("note") or "",
                idempotency_key=form.cleaned_data.get("idempotency_key") or None,
            )

            if mode == ClerkNewInvoiceForm.MODE_CREDIT:
                try:
                    receipt = payments.create_general_payment(**payment_kwargs)
                except payments.PaymentError as exc:
                    messages.error(request, str(exc))
                else:
                    messages.success(request, f"Receipt {receipt.number} created (student credit).")
                    return redirect("finance:payment_receipt_pdf", pk=receipt.pk)
            else:
                period = form.cleaned_data["billing_period"]
                breakdown = form.cleaned_data["breakdown"]
                created = []
                errors = []
                for category, rule, cat_amount in breakdown:
                    try:
                        invoice = invoicing.create_invoice(
                            student=student,
                            rule=rule,
                            period=period,
                            actor=request.user,
                            request=request,
                        )
                        created.append(invoice)
                    except Exception as e:
                        errors.append(f"{category.name}: {e}")

                if errors:
                    for e in errors:
                        messages.error(request, e)
                else:
                    receipts = []
                    remaining = amount
                    for invoice in created:
                        if remaining <= 0:
                            break
                        apply = min(remaining, invoice.balance)
                        try:
                            r = payments.record_payment(
                                invoice=invoice,
                                amount=apply,
                                method=method,
                                reference=payment_kwargs["reference"],
                                note=payment_kwargs["note"],
                                actor=request.user,
                                auto_approve=True,
                            )
                            receipts.append(r)
                            remaining -= apply
                        except payments.PaymentError as exc:
                            messages.warning(request, str(exc))
                    
                    messages.success(
                        request,
                        f"Created {len(created)} invoice(s)"
                        + (f", recorded {len(receipts)} payment(s)." if receipts else "."),
                    )
                    if receipts:
                        return redirect("finance:payment_receipt_pdf", pk=receipts[0].pk)
                    return redirect("finance:invoice_list")
        messages.error(request, "Please fix the errors below.")
    else:
        form = ClerkNewInvoiceForm()
    return render(request, "finance/clerk_new_invoice.html", {"form": form})


# ---- payment receive / receipt PDF ---------------------------------------------------------

@finance_permission_required("view_finance")
def payment_receive(request, invoice_pk):
    invoice = get_object_or_404(StudentInvoice, pk=invoice_pk)

    if request.method == "POST":
        form = PaymentReceiptForm(request.POST, invoice=invoice)
        if form.is_valid():
            try:
                receipt = payments.record_payment(
                    invoice=invoice,
                    amount=form.cleaned_data["amount"],
                    method=form.cleaned_data["method"],
                    reference=form.cleaned_data.get("reference", ""),
                    note=form.cleaned_data.get("note", ""),
                    actor=request.user,
                    auto_approve=(request.user.role in ("ADMIN", "ACCOUNTANT")),
                )
                messages.success(request, f"Receipt {receipt.number} created.")
                return redirect("finance:payment_receipt_pdf", pk=receipt.pk)
            except payments.PaymentError as e:
                messages.error(request, str(e))
    else:
        form = PaymentReceiptForm(invoice=invoice)

    return render(request, "finance/payment_receive.html", {
        "invoice": invoice,
        "form": form,
    })


@finance_permission_required("view_finance")
def payment_receipt_pdf(request, pk):
    from .pdf import render_receipt_pdf

    receipt = get_object_or_404(PaymentReceipt, pk=pk)
    if receipt.status not in (PaymentReceipt.Status.APPROVED, PaymentReceipt.Status.ACTIVE):
        messages.error(request, "Receipt is not yet approved.")
        return redirect("finance:invoice_detail", pk=receipt.invoice_id)

    pdf_bytes = render_receipt_pdf(receipt, requested_by=request.user)
    filename = f"receipt_{receipt.number}.pdf"
    return FileResponse(
        iter([pdf_bytes]),
        content_type="application/pdf",
        as_attachment=True,
        filename=filename,
    )


# ---- allocation dashboard / form ----------------------------------------------------------

@finance_permission_required("allocate_payment")
def allocation_dashboard(request):
    students = (
        Student.objects
        .filter(payment_receipts__status=PaymentReceipt.Status.ACTIVE)
        .select_related("class_ref")
        .distinct()
        .order_by("class_ref", "roll_no")
    )
    rows = []
    for student in students:
        credit = payments.available_credit(student)
        open_count = (
            StudentInvoice.objects
            .filter(student=student, balance__gt=0)
            .exclude(status=StudentInvoice.Status.CANCELLED)
            .count()
        )
        if credit > 0 or open_count > 0:
            rows.append({"student": student, "credit": credit, "open_invoices": open_count})
    return render(request, "finance/allocation_dashboard.html", {"rows": rows})


@finance_permission_required("allocate_payment")
def allocation_form(request, student_pk):
    student = get_object_or_404(Student, pk=student_pk)
    if request.method == "POST":
        form = AllocationForm(request.POST, student=student)
        if form.is_valid():
            try:
                allocation = payments.allocate_payment(
                    payment=form.cleaned_data["payment"],
                    invoice=form.cleaned_data["invoice"],
                    amount=form.cleaned_data["amount"],
                    actor=request.user,
                    idempotency_key=form.cleaned_data.get("idempotency_key") or None,
                )
            except payments.PaymentError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, f"Allocated {allocation.amount} to {allocation.invoice.invoice_no}.")
                return redirect("finance:allocation_dashboard")
    else:
        form = AllocationForm(student=student)
    return render(request, "finance/allocation_form.html", {"form": form, "student": student})