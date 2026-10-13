"""Business logic: grading, GPA, report-card data, attendance summaries."""
from django.db.models import Count, Q, Sum

# (minimum percentage, grade, GPA points) – highest first. Used when the admin has
# not configured a GradeScale in the database.
DEFAULT_SCALE = [(90, "A+", 4.0), (80, "A", 3.75), (70, "B", 3.0),
                 (60, "C", 2.0), (50, "D", 1.0), (0, "F", 0.0)]


def get_scale():
    from .models import GradeScale
    rows = [(float(g.min_percent), g.grade, float(g.gpa_points)) for g in GradeScale.objects.all()]
    return rows or DEFAULT_SCALE


def grade_for(percentage, scale=None):
    """Return (grade, gpa_points) for a percentage."""
    scale = scale or get_scale()
    pct = round(percentage, 2)
    for minimum, grade, points in scale:
        if pct >= minimum:
            return grade, points
    return scale[-1][1], scale[-1][2]


def class_rank(student, exam):
    """Rank of the student within their class for an exam (approved marks only)."""
    from .models import Marksheet
    totals = (Marksheet.objects
              .filter(exam=exam, status=Marksheet.Status.APPROVED,
                      student__class_ref=student.class_ref)
              .values("student").annotate(obt=Sum("marks_obtained"), mx=Sum("max_marks")))
    scores = {t["student"]: (float(t["obt"]) / float(t["mx"]) if t["mx"] else 0) for t in totals}
    if student.pk not in scores:
        return None, len(scores)
    mine = scores[student.pk]
    return 1 + sum(1 for s in scores.values() if s > mine), len(scores)


def build_report_data(student, exam):
    """Collect everything the report card needs. Returns None if no approved marks."""
    from .models import Marksheet
    sheets = (Marksheet.objects
              .filter(student=student, exam=exam, status=Marksheet.Status.APPROVED)
              .select_related("subject").order_by("subject__name"))
    if not sheets:
        return None
    scale = get_scale()
    rows, total_obt, total_max, gpa_sum = [], 0.0, 0.0, 0.0
    for s in sheets:
        pct = s.percentage
        grade, points = grade_for(pct, scale)
        rows.append({"subject": s.subject.name, "code": s.subject.code,
                     "obtained": float(s.marks_obtained), "max": float(s.max_marks),
                     "percentage": round(pct, 1), "grade": grade, "gpa": points})
        total_obt += float(s.marks_obtained)
        total_max += float(s.max_marks)
        gpa_sum += points
    percentage = total_obt / total_max * 100 if total_max else 0.0
    rank, class_size = class_rank(student, exam)
    return {
        "student": student, "exam": exam, "rows": rows,
        "total_obtained": total_obt, "total_max": total_max,
        "percentage": round(percentage, 2), "grade": grade_for(percentage, scale)[0],
        "gpa": round(gpa_sum / len(rows), 2), "rank": rank, "class_size": class_size,
    }


def attendance_summary(student, since=None):
    """Counts + attendance rate. LATE counts as attended (the child was there)."""
    from .models import Attendance
    qs = Attendance.objects.filter(student=student)
    if since:
        qs = qs.filter(date__gte=since)
    agg = qs.aggregate(
        total=Count("id"),
        present=Count("id", filter=Q(status="PRESENT")),
        absent=Count("id", filter=Q(status="ABSENT")),
        late=Count("id", filter=Q(status="LATE")),
        excused=Count("id", filter=Q(status="EXCUSED")),
    )
    agg["percent"] = round((agg["present"] + agg["late"]) / agg["total"] * 100, 1) if agg["total"] else None
    return agg



def build_merit_list(exam, class_ref):
    """Return a ranked list of students in a class for one exam.

    Each row: {rank, student, total_obtained, total_max, percentage, grade, gpa}
    Rows are sorted highest percentage first. Ties share the same rank.
    """
    from students.models import Student

    students = class_ref.students.filter(is_active=True).order_by("roll_no")
    rows = []
    for st in students:
        data = build_report_data(st, exam)
        if data is None:
            continue
        rows.append({
            "student": st,
            "total_obtained": data["total_obtained"],
            "total_max": data["total_max"],
            "percentage": data["percentage"],
            "grade": data["grade"],
            "gpa": data["gpa"],
        })

    # Sort by percentage, descending
    rows.sort(key=lambda r: r["percentage"], reverse=True)

    # Assign ranks. Tied percentages share the same rank.
    previous_pct = None
    previous_rank = 0
    for i, row in enumerate(rows, start=1):
        if previous_pct is not None and abs(row["percentage"] - previous_pct) < 0.01:
            row["rank"] = previous_rank
        else:
            row["rank"] = i
            previous_rank = i
        previous_pct = row["percentage"]

    return rows
