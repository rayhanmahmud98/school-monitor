from django.contrib import admin

from .models import (
    LeaveApplication,
    ExamType,AcademicYear, Attendance, AuditLog, Exam, GradeScale, Marksheet,
                     ReportCard)
from .models import SchoolProfile, IDCard



@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ("name", "is_current")


@admin.register(GradeScale)
class GradeScaleAdmin(admin.ModelAdmin):
    list_display = ("grade", "min_percent", "gpa_points")


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ("name", "academic_year", "start_date", "end_date", "is_published")
    list_filter = ("academic_year", "is_published")


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("student", "date", "status", "marked_by", "marked_at")
    list_filter = ("status", "date", "student__class_ref")
    search_fields = ("student__full_name",)


@admin.register(Marksheet)
class MarksheetAdmin(admin.ModelAdmin):
    list_display = ("student", "subject", "exam", "marks_obtained", "max_marks", "grade", "status")
    list_filter = ("status", "exam", "subject__class_ref")
    search_fields = ("student__full_name",)


@admin.register(ReportCard)
class ReportCardAdmin(admin.ModelAdmin):
    list_display = ("student", "exam", "generated_at", "published_at", "published_by")
    list_filter = ("exam",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "user", "action", "target_model", "target_id", "ip_address")
    list_filter = ("action", "user")
    search_fields = ("details", "action")
    readonly_fields = [f.name for f in AuditLog._meta.fields]


@admin.register(ExamType)
class ExamTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "weight", "is_active", "exam_count")
    list_filter = ("is_active",)
    search_fields = ("name", "description")

    @admin.display(description="Exams")
    def exam_count(self, obj):
        return obj.exams.count()


@admin.register(LeaveApplication)
class LeaveApplicationAdmin(admin.ModelAdmin):
    list_display = ("applicant_display", "applicant_type", "start_date", "end_date",
                    "days_count", "status", "reviewed_by")
    list_filter = ("status", "applicant_type", "start_date")
    search_fields = ("student__full_name", "teacher__username", "reason")
    date_hierarchy = "start_date"
    readonly_fields = ("submitted_at", "reviewed_at")



@admin.register(SchoolProfile)
class SchoolProfileAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        # Prevent adding a second profile
        return not SchoolProfile.objects.exists()

@admin.register(IDCard)
class IDCardAdmin(admin.ModelAdmin):
    list_display = ("kind", "display_owner", "uuid", "issued_at", "revoked_at")
    list_filter = ("kind", "revoked_at")
    search_fields = ("uuid", "student__full_name", "teacher__username")
    readonly_fields = ("uuid", "issued_at")

    @admin.display(description="Owner")
    def display_owner(self, obj):
        if obj.student: return obj.student.full_name
        if obj.teacher: return obj.teacher.display_name
        return "-"