from django.urls import path

from . import views

app_name = "academics"

urlpatterns = [
    # --- Attendance ---
    path("attendance/", views.attendance_list, name="attendance_list"),
    path("attendance/mark/", views.attendance_mark, name="attendance_mark"),
    path("attendance/<int:pk>/edit/", views.attendance_edit, name="attendance_edit"),

    # --- Marksheets ---
    path("marks/", views.marks_overview, name="marks_overview"),
    path("marks/<int:subject_id>/<int:exam_id>/enter/",
         views.marks_enter, name="marks_enter"),
    path("marks/<int:subject_id>/<int:exam_id>/review/",
         views.marks_review, name="marks_review"),

    # --- Report cards ---
    path("report-cards/", views.reportcards_manage, name="reportcards_manage"),
    path("report-cards/<int:pk>/download/",
         views.reportcard_download, name="reportcard_download"),

    # --- Parent views ---
    path("parent/attendance/", views.parent_attendance, name="parent_attendance"),
    path("parent/marks/", views.parent_marks, name="parent_marks"),
    path("parent/report-cards/", views.parent_reportcards, name="parent_reportcards"),

    # --- Audit log (admin only) ---
    path("audit-log/", views.audit_log, name="audit_log"),

    # --- Student progress PDF (admin / teacher / parent) ---
    path("students/<int:student_pk>/admit-card/",
         views.admit_card_page, name="admit_card_page"),
    path("students/<int:student_pk>/admit-card/<int:exam_pk>.pdf",
         views.admit_card_download, name="admit_card_download"),
    path("admit-cards/",
         views.admit_cards_bulk_page, name="admit_cards_bulk_page"),
    path("leaves/", views.leave_list, name="leave_list"),
    path("leaves/new/", views.leave_create, name="leave_create"),
    path("leaves/<int:pk>/review/", views.leave_review, name="leave_review"),

    path("merit-list/",
         views.merit_list_view, name="merit_list"),
    path("merit-list/classes/<int:class_pk>/exams/<int:exam_pk>.pdf",
         views.merit_list_download, name="merit_list_download"),
    path("classes/<int:class_pk>/admit-cards/<int:exam_pk>.pdf",
         views.admit_cards_bulk, name="admit_cards_bulk"),

    path("students/<int:student_pk>/progress.pdf",
         views.student_progress_pdf, name="student_progress_pdf"),

    # --- CRUD routes from build_crud ---
    *views.exams.urls,
    *views.years.urls,
    *views.scales.urls,
    *views.exam_types.urls,
]