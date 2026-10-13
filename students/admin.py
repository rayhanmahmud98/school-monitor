from django.contrib import admin
from django.utils.html import format_html

from .models import (
    TransferCertificate,
    AcademicHistory,
    Class,
    EmergencyContact,
    Enrollment,
    ParentStudentLink,
    Student,
    StudentDocument,
    Subject,
)


@admin.register(Class)
class ClassAdmin(admin.ModelAdmin):
    list_display = ("name", "section", "academic_year")
    list_filter = ("academic_year", "section")
    search_fields = ("name", "section")


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "class_ref", "teacher")
    list_filter = ("class_ref",)
    search_fields = ("name", "code")


class EmergencyContactInline(admin.TabularInline):
    model = EmergencyContact
    extra = 1


class EnrollmentInline(admin.TabularInline):
    model = Enrollment
    extra = 0
    autocomplete_fields = ("class_ref",)


class AcademicHistoryInline(admin.TabularInline):
    model = AcademicHistory
    extra = 0


class StudentDocumentInline(admin.TabularInline):
    model = StudentDocument
    extra = 0
    readonly_fields = ("uploaded_at",)


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = (
        "student_id", "photo_thumb", "full_name", "roll_no", "class_ref",
        "blood_group", "gender", "is_active",
    )
    list_filter = ("class_ref", "is_active", "blood_group", "gender")
    search_fields = ("student_id", "full_name", "first_name", "last_name",
                     "guardian_name", "email", "phone", "roll_no")
    readonly_fields = ("student_id", "full_name", "photo_preview")
    inlines = (
        EmergencyContactInline,
        EnrollmentInline,
        AcademicHistoryInline,
        StudentDocumentInline,
    )
    fieldsets = (
        ("Identification", {
            "fields": ("student_id", "first_name", "middle_name", "last_name",
                       "preferred_name", "full_name", "photo", "photo_preview",
                       "blood_group"),
        }),
        ("Demographics", {
            "fields": ("date_of_birth", "gender", "nationality", "ethnicity", "religion"),
        }),
        ("Academic placement", {
            "fields": ("class_ref", "roll_no", "admission_date", "is_active"),
        }),
        ("Contact", {
            "fields": ("address_line1", "address_line2", "city", "postal_code",
                       "mailing_address", "phone", "email"),
        }),
        ("Guardian quick reference", {
            "fields": ("guardian_name", "contact", "user_link"),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="Photo")
    def photo_thumb(self, obj):
        if obj.photo:
            return format_html(
                '<img src="{}" style="height:36px;width:36px;border-radius:9999px;object-fit:cover;" />',
                obj.photo.url,
            )
        return "—"

    @admin.display(description="Current photo")
    def photo_preview(self, obj):
        if obj.photo:
            return format_html(
                '<img src="{}" style="max-height:180px;border-radius:8px;" />',
                obj.photo.url,
            )
        return "No photo uploaded."


@admin.register(ParentStudentLink)
class ParentStudentLinkAdmin(admin.ModelAdmin):
    list_display = ("parent", "student", "relationship", "is_primary")
    list_filter = ("relationship", "is_primary")
    search_fields = ("parent__username", "student__full_name", "student__student_id")


@admin.register(EmergencyContact)
class EmergencyContactAdmin(admin.ModelAdmin):
    list_display = ("name", "student", "relationship", "phone", "is_primary")
    search_fields = ("name", "phone", "student__full_name")


@admin.register(AcademicHistory)
class AcademicHistoryAdmin(admin.ModelAdmin):
    list_display = ("student", "school_name", "year", "grade_level", "result")
    search_fields = ("student__full_name", "school_name")


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("student", "class_ref", "enrolled_on", "left_on", "is_current")
    list_filter = ("is_current", "class_ref")
    search_fields = ("student__full_name", "student__student_id")
    autocomplete_fields = ("class_ref",)


@admin.register(StudentDocument)
class StudentDocumentAdmin(admin.ModelAdmin):
    list_display = ("student", "kind", "display_title", "uploaded_at", "uploaded_by")
    list_filter = ("kind", "uploaded_at")
    search_fields = ("student__full_name", "student__student_id", "title", "notes")
    date_hierarchy = "uploaded_at"
    readonly_fields = ("uploaded_at",)

@admin.register(TransferCertificate)
class TransferCertificateAdmin(admin.ModelAdmin):
    list_display = ("tc_number", "student", "reason", "date_of_leaving",
                    "dues_cleared", "issued_at", "issued_by")
    list_filter = ("reason", "dues_cleared", "issued_at")
    search_fields = ("tc_number", "student__full_name", "student__student_id", "reason_note")
    date_hierarchy = "issued_at"
    readonly_fields = ("tc_number", "issued_at")
