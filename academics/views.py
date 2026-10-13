"""
Attendance, marksheets, report cards, parent views, audit log and settings CRUD.

Permission model:
  * every view is wrapped in @role_required (HTTP 403 for the wrong role)
  * data is fetched through accounts.scope helpers, so teachers only reach their own
    classes/subjects and parents only reach their linked children.
"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.crud import build_crud
from accounts.models import User
from accounts.permissions import ADMIN, PARENT, TEACHER, role_required
from accounts.scope import (parent_students, scoped_students, teacher_classes,
                            teacher_subjects)
from accounts.utils import paginate
from students.models import Class, Subject

from .audit import log_action
from .forms import (AcademicYearForm, AttendanceEditForm, ExamForm,
                    ExamTypeForm, GradeScaleForm, LeaveApplicationForm)
from .models import (
    AcademicYear, Attendance, AuditLog, Exam, ExamType, GradeScale,
    LeaveApplication, Marksheet, ReportCard,
)
from .pdf import render_report_card_pdf
from .services import attendance_summary, build_report_data

# --- Admin CRUD: exams + system settings ---------------------------------------
exams = build_crud(
    ns="academics", name="exam", slug="exams", model_class=Exam, form_cls=ExamForm,
    title="Exams", singular="Exam",
    columns=[("Exam", "name"), ("Academic year", "academic_year"), ("Start", "start_date"),
             ("End", "end_date"), ("Published", "is_published")],
    search_fields=("name", "academic_year"),
)
years = build_crud(
    ns="academics", name="year", slug="settings/years", model_class=AcademicYear,
    form_cls=AcademicYearForm, title="Academic Years", singular="Academic year",
    columns=[("Academic year", "name"), ("Current", "is_current")],
)
scales = build_crud(
    ns="academics", name="scale", slug="settings/grading", model_class=GradeScale,
    form_cls=GradeScaleForm, title="Grading Scale", singular="Grade band",
    columns=[("Minimum %", "min_percent"), ("Grade", "grade"), ("GPA points", "gpa_points")],
)

exam_types = build_crud(
    ns="academics", name="examtype", slug="settings/exam-types", model_class=ExamType,
    form_cls=ExamTypeForm, title="Exam Types", singular="Exam type",
    columns=[("Name", "name"), ("Weight", "weight"),
             ("Active", "is_active"), ("Description", "description")],
    search_fields=("name", "description"),
)


def parse_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


# ==============================================================================
# ATTENDANCE
# ==============================================================================
@role_required(ADMIN, TEACHER)
def attendance_mark(request):
    """Mark/edit attendance for one class. Teachers: assigned classes, today only."""
    user = request.user
    is_admin = user.role == ADMIN
    classes = Class.objects.all() if is_admin else teacher_classes(user)
    today = timezone.localdate()
    data = request.POST if request.method == "POST" else request.GET

    day = today
    if is_admin and data.get("date"):
        day = parse_date(data["date"]) or today

    selected, rows = None, None
    class_id = data.get("class", "")
    if class_id:
        selected = classes.filter(pk=class_id).first() if class_id.isdigit() else None
        if selected is None:
            raise PermissionDenied  # class not in this teacher's scope
        students = list(selected.students.filter(is_active=True).order_by("roll_no"))
        existing = {a.student_id: a for a in
                    Attendance.objects.filter(student__in=students, date=day).select_related("marked_by")}

        if request.method == "POST":
            created = updated = skipped = 0
            valid = set(Attendance.Status.values)
            with transaction.atomic():
                for st in students:
                    status = request.POST.get(f"status_{st.pk}")
                    remarks = request.POST.get(f"remarks_{st.pk}", "").strip()[:255]
                    if status not in valid:
                        continue
                    rec = existing.get(st.pk)
                    if rec is None:
                        Attendance.objects.create(student=st, date=day, status=status,
                                                  remarks=remarks, marked_by=user)
                        created += 1
                    elif not is_admin and rec.marked_by_id != user.pk:
                        skipped += 1          # teachers may only edit their own entries
                    elif rec.status != status or rec.remarks != remarks:
                        old = rec.status
                        rec.status, rec.remarks = status, remarks
                        if not is_admin:       # admin override keeps the original marker
                            rec.marked_by, rec.marked_at = user, timezone.now()
                        rec.save()
                        updated += 1
                        if is_admin and old != status:
                            log_action(request, "ATTENDANCE_OVERRIDE", rec,
                                       f"{st.full_name} on {day}: {old} -> {status}")
                log_action(request, "ATTENDANCE_MARKED", selected,
                           f"{selected} on {day}: {created} created, {updated} updated, {skipped} skipped")
            messages.success(request, f"Attendance saved: {created} new, {updated} updated.")
            if skipped:
                messages.warning(request, f"{skipped} entries were marked by someone else and left unchanged.")
            return redirect(f"{request.path}?class={selected.pk}&date={day.isoformat()}")

        rows = []
        for st in students:
            rec = existing.get(st.pk)
            rows.append({
                "student": st, "rec": rec,
                "status": rec.status if rec else "PRESENT",
                "remarks": rec.remarks if rec else "",
                "locked": bool(rec and not is_admin and rec.marked_by_id != user.pk),
            })
    return render(request, "academics/attendance_mark.html", {
        "classes": classes, "selected": selected, "rows": rows, "day": day,
        "is_admin": is_admin, "today": today, "statuses": Attendance.Status.choices,
    })


@role_required(ADMIN, TEACHER)
def attendance_list(request):
    """Attendance history. Admin: everything. Teacher: only their own students."""
    user = request.user
    qs = (Attendance.objects.filter(student__in=scoped_students(user))
          .select_related("student", "student__class_ref", "marked_by"))
    classes = Class.objects.all() if user.role == ADMIN else teacher_classes(user)
    f = {k: request.GET.get(k, "").strip() for k in ("class", "q", "status", "from", "to")}
    if f["class"].isdigit():
        qs = qs.filter(student__class_ref_id=f["class"])
    if f["q"]:
        qs = qs.filter(student__full_name__icontains=f["q"])
    if f["status"] in Attendance.Status.values:
        qs = qs.filter(status=f["status"])
    if parse_date(f["from"]):
        qs = qs.filter(date__gte=parse_date(f["from"]))
    if parse_date(f["to"]):
        qs = qs.filter(date__lte=parse_date(f["to"]))
    page_obj, querystring = paginate(request, qs, 25)
    return render(request, "academics/attendance_list.html", {
        "page_obj": page_obj, "qs": querystring, "classes": classes, "f": f,
        "statuses": Attendance.Status.choices,
    })


@role_required(ADMIN)
def attendance_edit(request, pk):
    """Admin override of a single entry, recorded in the audit log."""
    rec = get_object_or_404(Attendance.objects.select_related("student", "marked_by"), pk=pk)
    old_status, old_remarks = rec.status, rec.remarks
    form = AttendanceEditForm(request.POST or None, instance=rec)
    if request.method == "POST" and form.is_valid():
        form.save()
        log_action(request, "ATTENDANCE_OVERRIDE", rec,
                   f"{rec.student.full_name} on {rec.date}: {old_status} -> {rec.status}"
                   f" (remarks: '{old_remarks}' -> '{rec.remarks}')")
        messages.success(request, "Attendance entry updated and logged.")
        return redirect("academics:attendance_list")
    return render(request, "crud/form.html", {
        "form": form, "title": f"Override attendance: {rec.student.full_name} ({rec.date})",
        "cancel_url": reverse("academics:attendance_list"),
    })


# ==============================================================================
# MARKSHEETS
# ==============================================================================
def build_batches(subjects_qs, exams_qs, only_existing):
    """One 'batch' = (subject, exam). Summarises entered/submitted/approved counts."""
    subjects_list = list(subjects_qs.select_related("class_ref", "teacher").annotate(
        student_count=Count("class_ref__students", filter=Q(class_ref__students__is_active=True),
                            distinct=True)))
    exams_list = list(exams_qs)
    counts = defaultdict(lambda: defaultdict(int))
    for r in (Marksheet.objects.filter(subject_id__in=[s.pk for s in subjects_list],
                                       exam_id__in=[e.pk for e in exams_list])
              .values("subject_id", "exam_id", "status").annotate(n=Count("id"))):
        counts[(r["subject_id"], r["exam_id"])][r["status"]] = r["n"]
    batches = []
    for subj in subjects_list:
        for exam in exams_list:
            c = counts[(subj.pk, exam.pk)]
            entered = sum(c.values())
            if only_existing and not entered:
                continue
            if c["SUBMITTED"]:
                state = "SUBMITTED"
            elif c["APPROVED"] and not c["DRAFT"]:
                state = "APPROVED"
            elif c["DRAFT"]:
                state = "DRAFT"
            else:
                state = "NOT_STARTED"
            batches.append({"subject": subj, "exam": exam, "total": subj.student_count,
                            "entered": entered, "submitted": c["SUBMITTED"],
                            "approved": c["APPROVED"], "state": state})
    return batches


STATE_LABELS = {"NOT_STARTED": "Not started", "DRAFT": "Draft", "SUBMITTED": "Awaiting approval",
                "APPROVED": "Approved"}


@role_required(ADMIN, TEACHER)
def marks_overview(request):
    user = request.user
    is_admin = user.role == ADMIN
    subjects_qs = Subject.objects.all() if is_admin else teacher_subjects(user)
    exams_qs = Exam.objects.all()
    f = {k: request.GET.get(k, "").strip() for k in ("class", "subject", "exam", "state")}
    if f["class"].isdigit():
        subjects_qs = subjects_qs.filter(class_ref_id=f["class"])
    if f["subject"].isdigit():
        subjects_qs = subjects_qs.filter(pk=f["subject"])
    if f["exam"].isdigit():
        exams_qs = exams_qs.filter(pk=f["exam"])
    batches = build_batches(subjects_qs, exams_qs, only_existing=is_admin)
    if f["state"] in STATE_LABELS:
        batches = [b for b in batches if b["state"] == f["state"]]
    for b in batches:
        b["state_label"] = STATE_LABELS[b["state"]]
    return render(request, "academics/marks_overview.html", {
        "batches": batches, "f": f, "is_admin": is_admin, "state_labels": STATE_LABELS,
        "classes": Class.objects.all() if is_admin else teacher_classes(user),
        "subjects": Subject.objects.select_related("class_ref") if is_admin else teacher_subjects(user),
        "exams": Exam.objects.all(),
    })


@role_required(TEACHER)
def marks_enter(request, subject_id, exam_id):
    """Teacher enters marks for ONE of their own subjects. Draft -> Submit (locks)."""
    subject = get_object_or_404(Subject.objects.select_related("class_ref"), pk=subject_id)
    if subject.teacher_id != request.user.pk:
        raise PermissionDenied  # cannot see/edit other teachers' subjects
    exam = get_object_or_404(Exam, pk=exam_id)
    students = list(subject.class_ref.students.filter(is_active=True).order_by("roll_no"))
    sheets = {m.student_id: m for m in Marksheet.objects.filter(subject=subject, exam=exam)}
    editable_ids = {s.pk for s in students if s.pk not in sheets or sheets[s.pk].status == "DRAFT"}
    first = next(iter(sheets.values()), None)
    max_marks = f"{first.max_marks:g}" if first else "100"
    posted = None

    if request.method == "POST":
        posted = request.POST
        action = posted.get("action")
        max_marks = posted.get("max_marks", max_marks).strip() or "100"
        errors, to_save = [], []
        try:
            max_value = Decimal(max_marks)
            if max_value <= 0:
                raise InvalidOperation
        except InvalidOperation:
            errors.append("Maximum marks must be a positive number.")
            max_value = Decimal(100)
        for st in students:
            if st.pk not in editable_ids:
                continue                      # submitted/approved rows are locked
            raw = posted.get(f"marks_{st.pk}", "").strip()
            if raw == "":
                if action == "submit":
                    errors.append(f"{st.full_name}: marks are required before submitting.")
                continue
            try:
                value = Decimal(raw)
            except InvalidOperation:
                errors.append(f"{st.full_name}: '{raw}' is not a number.")
                continue
            if value < 0 or value > max_value:
                errors.append(f"{st.full_name}: marks must be between 0 and {max_value:g}.")
                continue
            to_save.append((st, value))
        if action not in ("draft", "submit"):
            errors.append("Unknown action.")
        if not editable_ids:
            errors.append("All marks are already submitted or approved; editing is locked.")

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            now = timezone.now()
            with transaction.atomic():
                for st, value in to_save:
                    sheet = sheets.get(st.pk) or Marksheet(student=st, subject=subject, exam=exam)
                    sheet.marks_obtained, sheet.max_marks = value, max_value
                    sheet.entered_by = request.user
                    if action == "submit":
                        sheet.status, sheet.submitted_at, sheet.rejection_reason = "SUBMITTED", now, ""
                    else:
                        sheet.status = "DRAFT"
                    sheet.save()  # grade is auto-calculated in Marksheet.save()
                log_action(request, f"MARKS_{action.upper()}", subject,
                           f"{subject} / {exam}: {len(to_save)} marksheets")
            messages.success(request, "Marks submitted to admin for approval." if action == "submit"
                             else "Draft saved.")
            return redirect(request.path)

    rows = []
    for st in students:
        sheet = sheets.get(st.pk)
        editable = st.pk in editable_ids
        if posted is not None and editable:
            value = posted.get(f"marks_{st.pk}", "")
        else:
            value = f"{sheet.marks_obtained:g}" if sheet else ""
        rows.append({"student": st, "sheet": sheet, "editable": editable, "value": value})
    return render(request, "academics/marks_enter.html", {
        "subject": subject, "exam": exam, "rows": rows, "max_marks": max_marks,
        "any_editable": bool(editable_ids),
    })


@role_required(ADMIN)
def marks_review(request, subject_id, exam_id):
    """Admin reviews a batch; approve (locks) or reject with a reason."""
    subject = get_object_or_404(Subject.objects.select_related("class_ref", "teacher"), pk=subject_id)
    exam = get_object_or_404(Exam, pk=exam_id)
    sheets = Marksheet.objects.filter(subject=subject, exam=exam).select_related("student")
    if request.method == "POST":
        action = request.POST.get("action")
        pending = sheets.filter(status="SUBMITTED")
        if not pending.exists():
            messages.warning(request, "There are no submitted marksheets in this batch.")
        elif action == "approve":
            n = pending.update(status="APPROVED", approved_at=timezone.now(), approved_by=request.user)
            log_action(request, "MARKS_APPROVED", subject, f"{subject} / {exam}: {n} marksheets approved")
            messages.success(request, f"{n} marksheets approved and locked.")
        elif action == "reject":
            reason = request.POST.get("reason", "").strip()
            if not reason:
                messages.error(request, "A reason is required to reject marksheets.")
                return redirect(request.path)
            n = pending.update(status="DRAFT", rejection_reason=reason, submitted_at=None)
            log_action(request, "MARKS_REJECTED", subject, f"{subject} / {exam}: {n} rejected. Reason: {reason}")
            messages.success(request, f"{n} marksheets returned to the teacher.")
        return redirect(request.path)
    return render(request, "academics/marks_review.html", {
        "subject": subject, "exam": exam, "sheets": sheets.order_by("student__roll_no"),
        "pending": sheets.filter(status="SUBMITTED").count(),
    })


# ==============================================================================
# REPORT CARDS
# ==============================================================================
def _generate_report_card(student, exam):
    data = build_report_data(student, exam)
    if data is None:
        return None
    pdf_bytes = render_report_card_pdf(data)
    card, _ = ReportCard.objects.get_or_create(student=student, exam=exam)
    if card.pdf_file:
        card.pdf_file.delete(save=False)
    card.pdf_file.save(f"{exam.pk}_{student.class_ref_id}_{student.roll_no}.pdf",
                       ContentFile(pdf_bytes), save=True)
    return card


@role_required(ADMIN)
def reportcards_manage(request):
    """Generate, publish/unpublish and download report cards for a class + exam."""
    data = request.POST if request.method == "POST" else request.GET
    exam = Exam.objects.filter(pk=data["exam"]).first() if data.get("exam", "").isdigit() else None
    cls = Class.objects.filter(pk=data["class"]).first() if data.get("class", "").isdigit() else None

    if request.method == "POST" and exam and cls:
        action = request.POST.get("action")
        students = cls.students.filter(is_active=True)
        if request.POST.get("student", "").isdigit():
            students = students.filter(pk=request.POST["student"])
        done = skipped = 0
        for st in students:
            if action in ("generate", "generate_all"):
                if _generate_report_card(st, exam):
                    done += 1
                else:
                    skipped += 1
            elif action in ("publish", "publish_all", "unpublish"):
                card = ReportCard.objects.filter(student=st, exam=exam).exclude(pdf_file="").first()
                if not card:
                    skipped += 1
                    continue
                if action == "unpublish":
                    card.published_at, card.published_by = None, None
                else:
                    card.published_at, card.published_by = timezone.now(), request.user
                card.save()
                done += 1
        log_action(request, f"REPORTCARD_{(action or '').upper()}", exam,
                   f"{cls} / {exam}: {done} processed, {skipped} skipped")
        messages.success(request, f"{done} report card(s) processed.")
        if skipped:
            messages.warning(request, f"{skipped} skipped (no approved marks yet, or not generated).")
        return redirect(f"{request.path}?exam={exam.pk}&class={cls.pk}")

    rows = []
    if exam and cls:
        cards = {c.student_id: c for c in ReportCard.objects.filter(exam=exam, student__class_ref=cls)}
        approved = dict(Marksheet.objects.filter(exam=exam, student__class_ref=cls, status="APPROVED")
                        .values_list("student").annotate(n=Count("id")))
        for st in cls.students.filter(is_active=True).order_by("roll_no"):
            rows.append({"student": st, "card": cards.get(st.pk), "approved": approved.get(st.pk, 0)})
    return render(request, "academics/reportcards_manage.html", {
        "exams": Exam.objects.all(), "classes": Class.objects.all(),
        "exam": exam, "cls": cls, "rows": rows, "subject_count": cls.subjects.count() if cls else 0,
    })


@role_required(ADMIN, PARENT)
def reportcard_download(request, pk):
    card = get_object_or_404(ReportCard.objects.select_related("student", "exam"), pk=pk)
    if request.user.role == PARENT:
        # parents: only PUBLISHED cards of their OWN children
        if not card.is_published or not parent_students(request.user).filter(pk=card.student_id).exists():
            raise PermissionDenied
    if not card.pdf_file:
        raise Http404("This report card has not been generated yet.")
    filename = f"report_card_{card.student.full_name.replace(' ', '_')}_{card.exam.name}.pdf"
    return FileResponse(card.pdf_file.open("rb"), as_attachment=True, filename=filename,
                        content_type="application/pdf")


# ==============================================================================
# PARENT (read-only)
# ==============================================================================
def get_child(request):
    """Return (all linked children, selected child). Foreign ?child= ids give 403."""
    kids = parent_students(request.user).select_related("class_ref").order_by("full_name")
    cid = request.GET.get("child", "")
    if cid:
        child = kids.filter(pk=cid).first() if cid.isdigit() else None
        if child is None:
            raise PermissionDenied
    else:
        child = kids.first()
    return kids, child


@role_required(PARENT)
def parent_attendance(request):
    kids, child = get_child(request)
    ctx = {"kids": kids, "child": child}
    if child:
        since = timezone.localdate() - timedelta(days=60)
        records = Attendance.objects.filter(student=child, date__gte=since).order_by("-date")
        ctx.update(summary=attendance_summary(child), recent_summary=attendance_summary(child, since),
                   records=records)
    return render(request, "academics/parent_attendance.html", ctx)


@role_required(PARENT)
def parent_marks(request):
    kids, child = get_child(request)
    ctx = {"kids": kids, "child": child, "exams": [], "report": None}
    if child:
        exam_qs = Exam.objects.filter(is_published=True, marksheets__student=child,
                                      marksheets__status="APPROVED").distinct()
        ctx["exams"] = exam_qs
        exam = exam_qs.filter(pk=request.GET["exam"]).first() if request.GET.get("exam", "").isdigit() \
            else exam_qs.first()
        ctx["exam"] = exam
        if exam:
            ctx["report"] = build_report_data(child, exam)
    return render(request, "academics/parent_marks.html", ctx)


@role_required(PARENT)
def parent_reportcards(request):
    kids, child = get_child(request)
    cards = (ReportCard.objects.filter(student=child, published_at__isnull=False)
             .exclude(pdf_file="").select_related("exam") if child else [])
    return render(request, "academics/parent_reportcards.html",
                  {"kids": kids, "child": child, "cards": cards})


# ==============================================================================
# AUDIT LOG
# ==============================================================================
@role_required(ADMIN)
def audit_log(request):
    qs = AuditLog.objects.select_related("user")
    q = request.GET.get("q", "").strip()
    user_id = request.GET.get("user", "")
    if q:
        qs = qs.filter(Q(action__icontains=q) | Q(details__icontains=q) | Q(target_model__icontains=q))
    if user_id.isdigit():
        qs = qs.filter(user_id=user_id)
    page_obj, querystring = paginate(request, qs, 30)
    return render(request, "academics/audit_log.html", {
        "page_obj": page_obj, "qs": querystring, "q": q, "user_id": user_id,
        "users": User.objects.order_by("username"),
    })


# ==============================================================================
# STUDENT PROGRESS PDF (new)
# ==============================================================================
@role_required(ADMIN, TEACHER, PARENT)
def student_progress_pdf(request, student_pk):
    """A4 progress report for a single student.

    Admin   -> any student, any exam.
    Teacher -> students in classes they teach (via scoped_students).
    Parent  -> only their own children, any exam; otherwise "Nice Try Epstein!!!".
    """
    from students.models import ParentStudentLink

    from .pdf import render_progress_pdf

    user = request.user

    if user.role == PARENT:
        link = (
            ParentStudentLink.objects
            .select_related("student", "student__class_ref")
            .filter(parent=user, student_id=student_pk)
            .first()
        )
        if not link:
            return render(request, "academics/not_your_child.html", status=403)
        student = link.student
    else:
        student = get_object_or_404(scoped_students(user), pk=student_pk)

    exam_id = request.GET.get("exam", "").strip()
    exam = None
    if exam_id.isdigit():
        candidate = Exam.objects.filter(pk=exam_id).first()
        if candidate and student.marksheets.filter(exam=candidate).exists():
            exam = candidate

    pdf_bytes = render_progress_pdf(student, exam=exam, requested_by=user)

    if exam is not None:
        filename = f"progress_{exam.pk}_{student.class_ref_id}_{student.roll_no}.pdf"
    else:
        filename = f"progress_all_{student.class_ref_id}_{student.roll_no}.pdf"

    return FileResponse(
        iter([pdf_bytes]),
        content_type="application/pdf",
        as_attachment=True,
        filename=filename,
    )


# ==============================================================================
# ADMIT CARDS (new)
# ==============================================================================
@role_required(ADMIN, TEACHER, PARENT)
def admit_card_download(request, student_pk, exam_pk):
    """Download a single student's admit card for one exam.

    Admin/teacher: any student in scope, any exam.
    Parent: only their own children, only published exams.
    """
    from students.models import ParentStudentLink
    from .pdf import render_admit_card_pdf

    user = request.user

    if user.role == PARENT:
        link = (
            ParentStudentLink.objects
            .select_related("student", "student__class_ref")
            .filter(parent=user, student_id=student_pk)
            .first()
        )
        if not link:
            return render(request, "academics/not_your_child.html", status=403)
        student = link.student
    else:
        student = get_object_or_404(scoped_students(user), pk=student_pk)

    exam = get_object_or_404(Exam, pk=exam_pk)

    # Parents only see published exams
    if user.role == PARENT and not exam.is_published:
        return render(request, "academics/not_your_child.html", status=403)

    pdf_bytes = render_admit_card_pdf(student, exam, requested_by=user)
    filename = f"admit_card_{student.student_id or student.pk}_{exam.pk}.pdf"
    return FileResponse(
        iter([pdf_bytes]),
        content_type="application/pdf",
        as_attachment=True,
        filename=filename,
    )


@role_required(ADMIN)
def admit_cards_bulk(request, class_pk, exam_pk):
    """Download one PDF containing the admit cards of every active student in a class.

    The PDF has one admit card per page.
    """
    from .pdf import render_admit_card_pdf

    cls = get_object_or_404(Class, pk=class_pk)
    exam = get_object_or_404(Exam, pk=exam_pk)
    students_qs = cls.students.filter(is_active=True).order_by("roll_no")

    if not students_qs.exists():
        raise Http404("No active students in this class.")

    # Concatenate the PDFs generated for each student.
    from io import BytesIO
    from pypdf import PdfMerger

    merger = PdfMerger()
    for st in students_qs:
        merger.append(BytesIO(render_admit_card_pdf(st, exam, requested_by=request.user)))

    out = BytesIO()
    merger.write(out)
    merger.close()

    filename = f"admit_cards_class_{cls.pk}_exam_{exam.pk}.pdf"
    return FileResponse(
        iter([out.getvalue()]),
        content_type="application/pdf",
        as_attachment=True,
        filename=filename,
    )



@role_required(ADMIN, TEACHER, PARENT)
def admit_card_page(request, student_pk):
    """A small page with an exam picker; leads to the admit card PDF."""
    from students.models import ParentStudentLink

    user = request.user

    if user.role == PARENT:
        link = (
            ParentStudentLink.objects
            .select_related("student", "student__class_ref")
            .filter(parent=user, student_id=student_pk)
            .first()
        )
        if not link:
            return render(request, "academics/not_your_child.html", status=403)
        student = link.student
        exams = Exam.objects.filter(is_published=True).order_by("-start_date")
    else:
        student = get_object_or_404(scoped_students(user), pk=student_pk)
        exams = Exam.objects.order_by("-start_date")

    return render(request, "academics/admit_card_page.html", {
        "student": student,
        "exams": exams,
    })



@role_required(ADMIN)
def admit_cards_bulk_page(request):
    """Admin: pick a class and exam, then download all admit cards in one PDF."""
    classes_qs = Class.objects.all().order_by("name", "section")
    exams_qs = Exam.objects.order_by("-start_date")

    selected_class = None
    selected_exam = None
    count = 0

    class_id = request.GET.get("class", "").strip()
    exam_id = request.GET.get("exam", "").strip()

    if class_id.isdigit():
        selected_class = classes_qs.filter(pk=class_id).first()
        if selected_class:
            count = selected_class.students.filter(is_active=True).count()
    if exam_id.isdigit():
        selected_exam = exams_qs.filter(pk=exam_id).first()

    return render(request, "academics/admit_cards_bulk_page.html", {
        "classes": classes_qs,
        "exams": exams_qs,
        "selected_class": selected_class,
        "selected_exam": selected_exam,
        "count": count,
    })



# ==============================================================================
# MERIT LIST (new)
# ==============================================================================
@role_required(ADMIN, TEACHER)
def merit_list_view(request):
    """Pick a class and an exam, then view or download the merit list."""
    from .services import build_merit_list

    classes_qs = Class.objects.all().order_by("name", "section")
    exams_qs = Exam.objects.order_by("-start_date")

    if request.user.role == TEACHER:
        classes_qs = teacher_classes(request.user)

    selected_class = None
    selected_exam = None
    rows = []

    class_id = request.GET.get("class", "").strip()
    exam_id = request.GET.get("exam", "").strip()

    if class_id.isdigit():
        selected_class = classes_qs.filter(pk=class_id).first()
    if exam_id.isdigit():
        selected_exam = exams_qs.filter(pk=exam_id).first()

    if selected_class and selected_exam:
        rows = build_merit_list(selected_exam, selected_class)

    return render(request, "academics/merit_list.html", {
        "classes": classes_qs,
        "exams": exams_qs,
        "selected_class": selected_class,
        "selected_exam": selected_exam,
        "rows": rows,
    })


@role_required(ADMIN, TEACHER)
def merit_list_download(request, class_pk, exam_pk):
    """Stream the merit list PDF for a class + exam."""
    from .pdf import render_merit_list_pdf
    from .services import build_merit_list

    cls = get_object_or_404(Class, pk=class_pk)
    exam = get_object_or_404(Exam, pk=exam_pk)

    if request.user.role == TEACHER:
        allowed = set(teacher_classes(request.user).values_list("pk", flat=True))
        if cls.pk not in allowed:
            raise PermissionDenied

    rows = build_merit_list(exam, cls)
    pdf_bytes = render_merit_list_pdf(exam, cls, rows, requested_by=request.user)
    filename = f"merit_list_class_{cls.pk}_exam_{exam.pk}.pdf"
    return FileResponse(
        iter([pdf_bytes]),
        content_type="application/pdf",
        as_attachment=True,
        filename=filename,
    )



# ==============================================================================
# LEAVE APPLICATIONS (role-aware)
# ==============================================================================
def _leave_apply_to_attendance(leave, marked_by):
    """Write EXCUSED attendance rows for the weekdays in the leave range.

    Skips days that already have an attendance record.
    Returns (created_count, skipped_count).
    """
    if leave.applicant_type != LeaveApplication.Applicant.STUDENT or not leave.student:
        return (0, 0)

    created = skipped = 0
    day = leave.start_date
    while day <= leave.end_date:
        if day.weekday() < 5:   # skip weekends
            exists = Attendance.objects.filter(student=leave.student, date=day).exists()
            if exists:
                skipped += 1
            else:
                Attendance.objects.create(
                    student=leave.student,
                    date=day,
                    status=Attendance.Status.EXCUSED,
                    marked_by=marked_by,
                    remarks=f"Leave approved: {leave.reason[:120]}",
                )
                created += 1
        day += timedelta(days=1)
    return (created, skipped)


def _log_leave(request, action, leave, details=""):
    """Best-effort audit entry; never raises."""
    try:
        from .audit import log_action
        log_action(request, action, leave, details)
    except Exception:
        pass


@role_required(ADMIN, TEACHER, PARENT)
def leave_list(request):
    """Leave list scoped by role.

    Admin   -> all requests + pending count + Review buttons.
    Teacher -> their own requests only.
    Parent  -> their children's requests only.
    """
    user = request.user
    qs = LeaveApplication.objects.select_related(
        "student", "teacher", "reviewed_by", "submitted_by"
    )

    if user.role == TEACHER:
        qs = qs.filter(applicant_type=LeaveApplication.Applicant.TEACHER, teacher=user)

    elif user.role == PARENT:
        from students.models import ParentStudentLink
        child_ids = ParentStudentLink.objects.filter(parent=user).values_list("student_id", flat=True)
        qs = qs.filter(applicant_type=LeaveApplication.Applicant.STUDENT, student_id__in=child_ids)

    f_status = request.GET.get("status", "").strip()
    if f_status in LeaveApplication.Status.values:
        qs = qs.filter(status=f_status)

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(student__full_name__icontains=q)
            | Q(teacher__first_name__icontains=q)
            | Q(teacher__last_name__icontains=q)
            | Q(reason__icontains=q)
        )

    page_obj, querystring = paginate(request, qs, 25)

    pending_count = 0
    if user.role == ADMIN:
        pending_count = LeaveApplication.objects.filter(
            status=LeaveApplication.Status.PENDING
        ).count()

    # Page title and copy by role
    page_title = {
        "ADMIN": "Leave applications",
        "TEACHER": "My leave",
        "PARENT": "My child's leave",
    }.get(user.role, "Leave")

    page_subtitle = {
        "ADMIN": "Review and approve or reject leave requests.",
        "TEACHER": "Submit and track your own leave requests.",
        "PARENT": "Submit and track leave for your children.",
    }.get(user.role, "")

    return render(request, "academics/leave_list.html", {
        "page_obj": page_obj,
        "qs": querystring,
        "q": q,
        "f_status": f_status,
        "statuses": LeaveApplication.Status.choices,
        "pending_count": pending_count,
        "is_admin": user.role == ADMIN,
        "is_teacher": user.role == TEACHER,
        "is_parent": user.role == PARENT,
        "page_title": page_title,
        "page_subtitle": page_subtitle,
    })


@role_required(ADMIN, TEACHER, PARENT)
def leave_create(request):
    """Submit a leave request.

    Teacher -> for themselves only (form is prefilled and pickers are hidden).
    Parent  -> for one of their own children.
    Admin   -> for anyone (edge cases).
    """
    user = request.user

    if request.method == "POST":
        form = LeaveApplicationForm(request.POST, user=user)
        if form.is_valid():
            leave = form.save(commit=False)

            # Force role-appropriate values regardless of what the form submitted.
            if user.role == TEACHER:
                leave.applicant_type = LeaveApplication.Applicant.TEACHER
                leave.teacher = user
                leave.student = None
            elif user.role == PARENT:
                leave.applicant_type = LeaveApplication.Applicant.STUDENT
                leave.teacher = None
                # student came from the form, already validated against parent_students()
                # in the form's __init__.

            leave.submitted_by = user
            leave.save()

            _log_leave(
                request, "LEAVE_SUBMITTED", leave,
                f"{leave.applicant_display}: {leave.start_date} to {leave.end_date}"
                f" | submitted by {user.display_name}",
            )

            messages.success(request, "Leave request submitted. Waiting for admin approval.")
            return redirect("academics:leave_list")
        messages.error(request, "Please fix the errors below.")
    else:
        form = LeaveApplicationForm(user=user)

    return render(request, "academics/leave_form.html", {
        "form": form,
        "is_admin": user.role == ADMIN,
        "is_teacher": user.role == TEACHER,
        "is_parent": user.role == PARENT,
    })


@role_required(ADMIN)
def leave_review(request, pk):
    """Approve or reject a pending leave. On approval, excused attendance is written."""
    from .forms import LeaveReviewForm

    leave = get_object_or_404(
        LeaveApplication.objects.select_related("student", "teacher", "submitted_by"), pk=pk
    )

    if request.method == "POST":
        form = LeaveReviewForm(request.POST)
        if form.is_valid():
            action = form.cleaned_data["action"]
            note = form.cleaned_data["note"].strip()

            if action == "REJECT" and not note:
                messages.error(request, "A reason is required to reject a leave.")
            else:
                leave.status = (
                    LeaveApplication.Status.APPROVED if action == "APPROVE"
                    else LeaveApplication.Status.REJECTED
                )
                leave.review_note = note
                leave.reviewed_by = request.user
                leave.reviewed_at = timezone.now()
                leave.save()

                created = skipped = 0
                if action == "APPROVE":
                    created, skipped = _leave_apply_to_attendance(leave, request.user)

                _log_leave(
                    request,
                    f"LEAVE_{leave.status}",
                    leave,
                    f"{leave.applicant_display}: {leave.start_date} to {leave.end_date}"
                    + (f" | attendance created: {created}, skipped: {skipped}"
                       if action == "APPROVE" else f" | reason: {note[:120]}"),
                )

                msg = f"Leave {leave.status.lower()}."
                if action == "APPROVE":
                    msg += f" {created} excused attendance row(s) written."
                    if skipped:
                        msg += f" {skipped} day(s) already had records."
                messages.success(request, msg)
                return redirect("academics:leave_list")
    else:
        form = LeaveReviewForm(initial={"action": "APPROVE"})

    return render(request, "academics/leave_review.html", {
        "leave": leave,
        "form": form,
    })
