from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, F, Q
from django.shortcuts import redirect, render
from django.utils import timezone

from academics.models import Attendance, AuditLog, Exam, Marksheet, ReportCard
from academics.services import attendance_summary
from academics.views import build_batches, get_child
from accounts.models import User
from accounts.permissions import ADMIN, PARENT, TEACHER, role_required
from accounts.scope import teacher_classes, teacher_subjects
from students.models import Class, Student


@login_required
def home(request):
    """Send each user to the dashboard for their role."""
    target = {
        "ADMIN": "dashboard:admin",
        "TEACHER": "dashboard:teacher",
        "PARENT": "dashboard:parent",
    }
    return redirect(target.get(request.user.role, "accounts:login"))


def _month_starts(start, end):
    """Yield the first day of every month from start to end inclusive."""
    cur = start.replace(day=1)
    while cur <= end:
        yield cur
        if cur.month == 12:
            cur = cur.replace(year=cur.year + 1, month=1)
        else:
            cur = cur.replace(month=cur.month + 1)


@role_required(ADMIN)
def admin_dashboard(request):
    today = timezone.localdate()

    # --- Stat cards -------------------------------------------------------
    total_students = Student.objects.filter(is_active=True).count()
    total_teachers = User.objects.filter(role=TEACHER, is_active=True).count()
    total_parents = User.objects.filter(role=PARENT, is_active=True).count()
    total_classes = Class.objects.count()

    # Year-to-date attendance
    attended_total = Attendance.objects.filter(status__in=["PRESENT", "LATE"]).count()
    attendance_total = Attendance.objects.count()
    attendance_rate = round(attended_total / attendance_total * 100, 1) if attendance_total else None

    # Average grade percentage across all marksheets.
    # Use Decimal("100") instead of 100.0 so Django can infer the output field.
    avg_pct = (
        Marksheet.objects
        .annotate(pct=F("marks_obtained") * Decimal("100") / F("max_marks"))
        .aggregate(avg=Avg("pct"))["avg"]
    )
    avg_grade_percent = round(float(avg_pct), 1) if avg_pct is not None else None

    pending_batches = (
        Marksheet.objects.filter(status="SUBMITTED")
        .values("subject", "exam").distinct().count()
    )
    unpublished_cards = (
        ReportCard.objects.filter(published_at__isnull=True).exclude(pdf_file="").count()
    )

    # --- Attendance trend: last 6 months, bucketed by month ---------------
    six_months_ago = (today.replace(day=1) - timedelta(days=150)).replace(day=1)
    raw = (
        Attendance.objects
        .filter(date__gte=six_months_ago)
        .values("date")
        .annotate(
            attended=Count("id", filter=Q(status__in=["PRESENT", "LATE"])),
            total=Count("id"),
        )
        .order_by("date")
    )
    buckets = {}
    for row in raw:
        key = row["date"].replace(day=1).isoformat()
        b = buckets.setdefault(key, {"attended": 0, "total": 0})
        b["attended"] += row["attended"]
        b["total"] += row["total"]

    labels, rate_series = [], []
    for month_start in _month_starts(six_months_ago, today):
        key = month_start.isoformat()
        b = buckets.get(key, {"attended": 0, "total": 0})
        labels.append(month_start.strftime("%b %Y"))
        rate_series.append(round(b["attended"] / b["total"] * 100, 1) if b["total"] else 0)

    # --- Gender split (donut) --------------------------------------------
    gender_qs = (
        Student.objects.filter(is_active=True)
        .values("gender")
        .annotate(n=Count("id"))
        .order_by("gender")
    )
    gender_labels, gender_values = [], []
    for row in gender_qs:
        label = {"M": "Male", "F": "Female", "O": "Other", "": "Unspecified"}.get(
            row["gender"], "Unspecified"
        )
        gender_labels.append(label)
        gender_values.append(row["n"])

    # --- Students per class (bar) ----------------------------------------
    class_qs = (
        Class.objects
        .annotate(n=Count("students", filter=Q(students__is_active=True)))
        .order_by("name", "section")
    )
    class_labels = [str(c) for c in class_qs]
    class_values = [c.n for c in class_qs]

    # --- Recent activity for the footer table ----------------------------
    recent = AuditLog.objects.select_related("user")[:10]

    return render(request, "dashboard/admin.html", {
        # stat cards
        "students": total_students,
        "teachers": total_teachers,
        "parents": total_parents,
        "classes_count": total_classes,
        "attendance_percent": attendance_rate,
        "avg_grade_percent": avg_grade_percent,
        "pending_batches": pending_batches,
        "unpublished_cards": unpublished_cards,
        # today's snapshot for the small panel
        "attendance": Attendance.objects.filter(date=today).aggregate(
            total=Count("id"),
            attended=Count("id", filter=Q(status__in=["PRESENT", "LATE"])),
        ),
        # charts
        "chart_attendance_labels": labels,
        "chart_attendance_values": rate_series,
        "chart_gender_labels": gender_labels,
        "chart_gender_values": gender_values,
        "chart_class_labels": class_labels,
        "chart_class_values": class_values,
        # footer
        "recent": recent,
    })


@role_required(TEACHER)
def teacher_dashboard(request):
    user = request.user
    today = timezone.localdate()
    subjects = teacher_subjects(user)
    pending_attendance = []
    for cls in teacher_classes(user):
        active = cls.students.filter(is_active=True).count()
        marked = Attendance.objects.filter(student__class_ref=cls, date=today).count()
        if marked < active:
            pending_attendance.append({"cls": cls, "marked": marked, "total": active})
    batches = build_batches(subjects, Exam.objects.filter(is_published=False), only_existing=False)
    pending_marks = [b for b in batches if b["state"] in ("NOT_STARTED", "DRAFT")]
    return render(request, "dashboard/teacher.html", {
        "subjects": subjects,
        "classes": teacher_classes(user),
        "pending_attendance": pending_attendance,
        "pending_marks": pending_marks[:8],
        "pending_marks_count": len(pending_marks),
        "today": today,
    })


@role_required(PARENT)
def parent_dashboard(request):
    kids, child = get_child(request)
    ctx = {"kids": kids, "child": child}
    if child:
        since = timezone.localdate() - timedelta(days=30)
        ctx.update(
            summary=attendance_summary(child, since),
            recent=Attendance.objects.filter(student=child).order_by("-date")[:5],
            cards=ReportCard.objects.filter(student=child, published_at__isnull=False)
            .exclude(pdf_file="").select_related("exam"),
        )
    return render(request, "dashboard/parent.html", ctx)