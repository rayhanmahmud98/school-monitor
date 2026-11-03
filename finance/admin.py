"""Django admin: read-only inspection of financial records (changes go through the app)."""
from django.contrib import admin

from .models import (AuditEvent, FeeCategory, FeeRule, LedgerAccount, LedgerLine,
                     LedgerTransaction, StudentInvoice)


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FeeCategory)
class FeeCategoryAdmin(ReadOnlyAdmin):
    list_display = ("code", "name", "status", "default_frequency")


@admin.register(FeeRule)
class FeeRuleAdmin(ReadOnlyAdmin):
    list_display = ("fee_category", "academic_year", "class_ref", "amount", "effective_from", "effective_to")


@admin.register(StudentInvoice)
class StudentInvoiceAdmin(ReadOnlyAdmin):
    list_display = ("invoice_no", "student", "fee_category", "net_payable", "balance", "status")
    search_fields = ("invoice_no", "student__full_name", "student__student_id")


@admin.register(LedgerAccount)
class LedgerAccountAdmin(ReadOnlyAdmin):
    list_display = ("code", "name", "kind")


@admin.register(LedgerTransaction)
class LedgerTransactionAdmin(ReadOnlyAdmin):
    list_display = ("id", "tx_type", "posting_date", "description")


@admin.register(LedgerLine)
class LedgerLineAdmin(ReadOnlyAdmin):
    list_display = ("tx", "account", "debit", "credit")


@admin.register(AuditEvent)
class AuditEventAdmin(ReadOnlyAdmin):
    list_display = ("seq", "timestamp", "actor_label", "event_type", "object_type", "object_id")
