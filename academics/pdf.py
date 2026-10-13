"""PDF generation via ReportLab (pure Python – no system libraries needed)."""
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

INDIGO = colors.HexColor("#4338ca")
LIGHT = colors.HexColor("#eef2ff")
SLATE = colors.HexColor("#475569")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _photo_flowable(student, max_side_mm=28):
    """Return an Image flowable of the student's photo, or a placeholder Paragraph."""
    if student.photo and getattr(student.photo, "path", None):
        try:
            img = Image(student.photo.path)
            iw, ih = img.imageWidth, img.imageHeight
            scale = max_side_mm * mm / max(iw, ih)
            img.drawWidth, img.drawHeight = iw * scale, ih * scale
            return img
        except Exception:
            pass
    return Paragraph(
        '<para align="center"><font size="9" color="#94a3b8">No photo</font></para>',
        getSampleStyleSheet()["BodyText"],
    )


def _fmt_date(d):
    return d.strftime("%d %b %Y") if d else "-"


# ---------------------------------------------------------------------------
# Report card (existing) — one exam, one student
# ---------------------------------------------------------------------------
def render_report_card_pdf(data):
    """`data` comes from services.build_report_data(). Returns PDF bytes."""
    student, exam = data["student"], data["exam"]
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"Report Card - {student.full_name} - {exam.name}",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("t", parent=styles["Title"], textColor=INDIGO, fontSize=22)
    sub = ParagraphStyle("s", parent=styles["Heading3"], alignment=1, textColor=SLATE)
    story = [
        Paragraph("School Monitoring System", title),
        Paragraph(escape(f"Report Card - {exam.name} ({exam.academic_year})"), sub),
        Spacer(1, 6 * mm),
    ]

    info = [
        ["Student", student.full_name, "Roll No.", str(student.roll_no)],
        ["Class", str(student.class_ref), "Guardian", student.guardian_name],
        ["Date of birth", _fmt_date(student.date_of_birth), "Contact", student.contact],
    ]
    t = Table(info, colWidths=[28 * mm, 55 * mm, 25 * mm, 55 * mm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.lightgrey),
    ]))
    story += [t, Spacer(1, 7 * mm)]

    table = [["Subject", "Marks", "Out of", "%", "Grade", "GPA"]]
    for r in data["rows"]:
        table.append([
            r["subject"], f"{r['obtained']:g}", f"{r['max']:g}",
            f"{r['percentage']:.1f}", r["grade"], f"{r['gpa']:.2f}",
        ])
    table.append([
        "Total", f"{data['total_obtained']:g}", f"{data['total_max']:g}",
        f"{data['percentage']:.1f}", data["grade"], f"{data['gpa']:.2f}",
    ])
    mt = Table(
        table,
        colWidths=[60 * mm, 22 * mm, 22 * mm, 22 * mm, 20 * mm, 20 * mm],
        repeatRows=1,
    )
    mt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INDIGO),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f8fafc")]),
        ("BACKGROUND", (0, -1), (-1, -1), LIGHT),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [mt, Spacer(1, 8 * mm)]

    rank = f"{data['rank']} of {data['class_size']}" if data["rank"] else "-"
    summary = Table(
        [["Percentage", "Overall grade", "GPA", "Class rank"],
         [f"{data['percentage']:.2f}%", data["grade"], f"{data['gpa']:.2f}", rank]],
        colWidths=[42 * mm] * 4,
    )
    summary.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 1), (-1, 1), 14),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [
        summary,
        Spacer(1, 12 * mm),
        Paragraph(
            "This report card was generated electronically and reflects marks approved "
            "by the school administration.",
            styles["Italic"],
        ),
    ]
    doc.build(story)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Student progress report (new) — A4, one student, any / all exams
# ---------------------------------------------------------------------------
def render_progress_pdf(student, exam=None, requested_by=None):
    """Full A4 progress report for `student`.

    `exam` may be None -> the report covers all exams on record for this student.
    `requested_by` is used only in the footer (audit trail).
    """
    from django.db.models import Count, Q
    from django.utils import timezone as _tz

    from academics.models import Exam
    from academics.services import build_report_data

    buf = BytesIO()
    title_text = f"Progress Report - {student.full_name}"
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=14 * mm, bottomMargin=14 * mm,
        title=title_text,
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], textColor=INDIGO, fontSize=20)
    sub = ParagraphStyle("sub", parent=styles["Heading3"], alignment=1, textColor=SLATE)
    small = ParagraphStyle("small", parent=styles["BodyText"], fontSize=8, textColor=SLATE)
    label = ParagraphStyle("label", parent=styles["BodyText"], fontSize=8, textColor=SLATE)
    value = ParagraphStyle("value", parent=styles["BodyText"], fontSize=10)

    story = [
        Paragraph("School Monitoring System", h1),
        Paragraph(escape("Student Progress Report"), sub),
        Spacer(1, 5 * mm),
    ]

    # --- Header: photo + key details -------------------------------------
    photo = _photo_flowable(student)
    left = [
        ["Student ID", student.student_id or "-"],
        ["Name", student.full_name],
        ["Preferred name", student.preferred_name or "-"],
        ["Class", f"{student.class_ref}  |  Roll {student.roll_no}"],
        ["Blood group", student.blood_group or "-"],
        ["Gender", student.get_gender_display() if student.gender else "-"],
    ]
    left_tbl = Table(left, colWidths=[28 * mm, 70 * mm])
    left_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    header = Table([[photo, left_tbl]], colWidths=[34 * mm, 130 * mm])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [header, Spacer(1, 6 * mm)]

    # --- Guardian / contact block ---------------------------------------
    guardians = list(student.parent_links.select_related("parent").all())
    guardian_lines = []
    for g in guardians:
        phone = ""
        profile = getattr(g.parent, "parent_profile", None)
        if profile and profile.phone:
            phone = f" - {profile.phone}"
        guardian_lines.append(f"{g.parent.display_name} ({g.relationship or 'Guardian'}){phone}")
    if not guardian_lines:
        guardian_lines = ["-"]

    address = ", ".join(filter(None, [
        student.address_line1, student.address_line2, student.city, student.postal_code,
    ]))
    email_phone = ", ".join(filter(None, [student.email, student.phone]))

    contact = [
        ["Guardian(s)", "<br/>".join(escape(x) for x in guardian_lines)],
        ["Household contact", student.contact or "-"],
        ["Address", escape(address) or "-"],
        ["Email / Phone", escape(email_phone) or "-"],
    ]
    ct = Table(
        [[Paragraph(k, label), Paragraph(v, value)] for k, v in contact],
        colWidths=[34 * mm, 130 * mm],
    )
    ct.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.lightgrey),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story += [Paragraph("Guardian &amp; contact", styles["Heading4"]), ct, Spacer(1, 5 * mm)]

    # --- Attendance summary ---------------------------------------------
    att = student.attendance_records.aggregate(
        total=Count("id"),
        present=Count("id", filter=Q(status="PRESENT")),
        late=Count("id", filter=Q(status="LATE")),
        absent=Count("id", filter=Q(status="ABSENT")),
        excused=Count("id", filter=Q(status="EXCUSED")),
    )
    attended = (att["present"] or 0) + (att["late"] or 0)
    total = att["total"] or 0
    present_pct = (attended / total * 100) if total else 0.0

    att_tbl = Table(
        [["Present", "Late", "Absent", "Excused", "Total days", "% Present"],
         [att["present"] or 0, att["late"] or 0, att["absent"] or 0, att["excused"] or 0,
          total, f"{present_pct:.1f}%"]],
        colWidths=[27 * mm] * 5 + [30 * mm],
    )
    att_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [Paragraph("Attendance summary", styles["Heading4"]), att_tbl, Spacer(1, 6 * mm)]

    # --- Marks table ----------------------------------------------------
    if exam is not None:
        exams = [exam]
        scope_label = f"Exam: {exam.name} ({exam.academic_year})"
    else:
        exam_ids = list(student.marksheets.values_list("exam_id", flat=True).distinct())
        exams = list(Exam.objects.filter(pk__in=exam_ids).order_by("-start_date"))
        scope_label = "All exams on record"

    story += [
        Paragraph(f"Academic performance &mdash; {escape(scope_label)}", styles["Heading4"]),
    ]

    rows = [["Exam", "Subject", "Marks", "Max", "%", "Grade"]]
    for ex in exams:
        qs = (
            student.marksheets
            .select_related("subject", "exam")
            .filter(exam=ex)
            .order_by("subject__name")
        )
        for ms in qs:
            rows.append([
                ms.exam.name, ms.subject.name,
                f"{float(ms.marks_obtained):g}", f"{float(ms.max_marks):g}",
                f"{ms.percentage:.1f}", ms.grade or "-",
            ])
    if len(rows) == 1:
        rows.append(["—", "No marks on record", "", "", "", ""])

    mt = Table(
        rows,
        colWidths=[36 * mm, 50 * mm, 20 * mm, 20 * mm, 18 * mm, 20 * mm],
        repeatRows=1,
    )
    mt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INDIGO),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (2, 0), (-1, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [mt, Spacer(1, 6 * mm)]

    # --- Overall summary (single-exam mode only) ------------------------
    if exam is not None:
        try:
            data = build_report_data(student, exam)
            rank = f"{data['rank']} of {data['class_size']}" if data["rank"] else "-"
            summary = Table(
                [["Percentage", "Overall grade", "GPA", "Class rank"],
                 [f"{data['percentage']:.2f}%", data["grade"],
                  f"{data['gpa']:.2f}", rank]],
                colWidths=[42 * mm] * 4,
            )
            summary.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), LIGHT),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 1), (-1, 1), 12),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story += [summary, Spacer(1, 6 * mm)]
        except Exception:
            # build_report_data is optional; degrade gracefully.
            pass

    # --- Footer ---------------------------------------------------------
    generated = _tz.localtime().strftime("%d %b %Y %H:%M")
    by = requested_by.display_name if requested_by else "system"
    story += [
        Spacer(1, 4 * mm),
        Paragraph(
            escape(
                f"Generated by {by} on {generated}. "
                "This is a computer-generated progress report."
            ),
            small,
        ),
    ]

    doc.build(story)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Admit card (new) - A4, one per student per exam
# ---------------------------------------------------------------------------
def _safe_ascii(value):
    """Strip anything non-ASCII so ReportLab always renders."""
    if value is None:
        return "-"
    return str(value).encode("ascii", "replace").decode("ascii")


def render_admit_card_pdf(student, exam, requested_by=None):
    """Return PDF bytes for one student's admit card for one exam.

    Layout:
      - School header
      - Student identity block (photo, name, ID, class, roll)
      - Exam details block (name, academic year, dates)
      - Subject table with Date / Time / Room columns (blank unless schedules exist)
      - Instructions and signature line
    """
    from django.utils import timezone as _tz

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=14 * mm, bottomMargin=14 * mm,
        title=f"Admit Card - {student.full_name} - {exam.name}",
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1a", parent=styles["Title"], textColor=INDIGO, fontSize=20)
    sub = ParagraphStyle("suba", parent=styles["Heading3"], alignment=1, textColor=SLATE)
    small = ParagraphStyle("smalla", parent=styles["BodyText"], fontSize=8, textColor=SLATE)
    label = ParagraphStyle("labela", parent=styles["BodyText"], fontSize=8, textColor=SLATE)
    value = ParagraphStyle("valuea", parent=styles["BodyText"], fontSize=10)

    story = [
        Paragraph("School Monitoring System", h1),
        Paragraph("Admit Card", sub),
        Spacer(1, 4 * mm),
    ]

    # --- Student identity block -----------------------------------------
    photo = _photo_flowable(student)
    left = [
        ["Student ID", _safe_ascii(student.student_id)],
        ["Name", _safe_ascii(student.full_name)],
        ["Class", _safe_ascii(f"{student.class_ref}  |  Roll {student.roll_no}")],
        ["Blood group", _safe_ascii(student.blood_group)],
        ["Guardian", _safe_ascii(student.guardian_name)],
    ]
    left_tbl = Table(left, colWidths=[28 * mm, 70 * mm])
    left_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    header = Table([[photo, left_tbl]], colWidths=[34 * mm, 130 * mm])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [header, Spacer(1, 6 * mm)]

    # --- Exam details block ---------------------------------------------
    exam_details = [
        ["Exam", _safe_ascii(exam.name)],
        ["Academic year", _safe_ascii(exam.academic_year)],
        ["Start date", _safe_ascii(exam.start_date.strftime("%d %b %Y") if exam.start_date else "-")],
        ["End date", _safe_ascii(exam.end_date.strftime("%d %b %Y") if exam.end_date else "-")],
    ]
    ex_tbl = Table(
        [[Paragraph(k, label), Paragraph(v, value)] for k, v in exam_details],
        colWidths=[34 * mm, 130 * mm],
    )
    ex_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.lightgrey),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story += [Paragraph("Exam details", styles["Heading4"]), ex_tbl, Spacer(1, 5 * mm)]

    # --- Subject table --------------------------------------------------
    subjects = student.class_ref.subjects.order_by("name")
    rows = [["#", "Subject", "Code", "Date", "Time", "Room"]]
    for i, subj in enumerate(subjects, start=1):
        rows.append([str(i), _safe_ascii(subj.name), _safe_ascii(subj.code), "", "", ""])
    if len(rows) == 1:
        rows.append(["-", "No subjects listed for this class.", "", "", "", ""])

    st = Table(rows, colWidths=[10 * mm, 60 * mm, 25 * mm, 30 * mm, 25 * mm, 24 * mm], repeatRows=1)
    st.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INDIGO),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (3, 0), (-1, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [Paragraph("Subjects", styles["Heading4"]), st, Spacer(1, 5 * mm)]

    # --- Instructions ---------------------------------------------------
    story += [
        Paragraph("Instructions", styles["Heading4"]),
        Paragraph(
            "1. Bring this admit card to every exam. "
            "2. Arrive at least 15 minutes before the start time. "
            "3. Mobile phones and smart devices are not permitted in the exam hall. "
            "4. Follow the invigilator's instructions at all times.",
            small,
        ),
        Spacer(1, 12 * mm),
    ]

    # --- Signature line -------------------------------------------------
    sig = Table(
        [["_________________________", "", "_________________________"],
         ["Student's signature", "", "Principal's signature"]],
        colWidths=[55 * mm, 30 * mm, 55 * mm],
    )
    sig.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TEXTCOLOR", (0, 0), (-1, -1), SLATE),
        ("TOPPADDING", (0, 0), (-1, 0), 0),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 0),
    ]))
    story += [sig]

    # --- Footer ---------------------------------------------------------
    generated = _tz.localtime().strftime("%d %b %Y %H:%M")
    by = _safe_ascii(requested_by.display_name) if requested_by else "system"
    story += [
        Spacer(1, 4 * mm),
        Paragraph(
            _safe_ascii(f"Generated by {by} on {generated}. "
                        "This is a computer-generated admit card."),
            small,
        ),
    ]

    doc.build(story)
    return buf.getvalue()



# ---------------------------------------------------------------------------
# Merit list (new) - A4, one class + one exam per page
# ---------------------------------------------------------------------------
def render_merit_list_pdf(exam, class_ref, rows, requested_by=None):
    """Return PDF bytes for a merit list.

    rows: list of dicts from services.build_merit_list()
    """
    from django.utils import timezone as _tz

    def safe(v):
        if v is None:
            return "-"
        return str(v).encode("ascii", "replace").decode("ascii")

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=14 * mm, bottomMargin=14 * mm,
        title=f"Merit List - {class_ref} - {exam.name}",
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1m", parent=styles["Title"], textColor=INDIGO, fontSize=20)
    sub = ParagraphStyle("subm", parent=styles["Heading3"], alignment=1, textColor=SLATE)
    small = ParagraphStyle("smallm", parent=styles["BodyText"], fontSize=8, textColor=SLATE)

    story = [
        Paragraph("School Monitoring System", h1),
        Paragraph("Merit List", sub),
        Spacer(1, 4 * mm),
    ]

    # Exam and class block
    meta = [
        ["Exam", safe(exam.name)],
        ["Type", safe(getattr(exam.exam_type, "name", "-") if exam.exam_type_id else "-")],
        ["Academic year", safe(exam.academic_year)],
        ["Class", safe(str(class_ref))],
        ["Students ranked", str(len(rows))],
    ]
    mt = Table(meta, colWidths=[40 * mm, 120 * mm])
    mt.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [mt, Spacer(1, 6 * mm)]

    # Rankings table
    table = [["Rank", "Roll", "Student", "Total", "Max", "%", "Grade", "GPA"]]
    for r in rows:
        table.append([
            str(r["rank"]),
            str(r["student"].roll_no),
            safe(r["student"].full_name),
            f"{float(r['total_obtained']):g}",
            f"{float(r['total_max']):g}",
            f"{r['percentage']:.2f}",
            safe(r["grade"]),
            f"{r['gpa']:.2f}",
        ])
    if len(table) == 1:
        table.append(["-", "", "No approved marks for this exam.", "", "", "", "", ""])

    t = Table(
        table,
        colWidths=[16 * mm, 14 * mm, 60 * mm, 18 * mm, 18 * mm, 18 * mm, 18 * mm, 18 * mm],
        repeatRows=1,
    )
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INDIGO),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (1, -1), "CENTER"),
        ("ALIGN", (3, 0), (-1, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [t, Spacer(1, 6 * mm)]

    generated = _tz.localtime().strftime("%d %b %Y %H:%M")
    by = safe(requested_by.display_name) if requested_by else "system"
    story += [
        Paragraph(
            safe(f"Generated by {by} on {generated}. "
                 "This is a computer-generated merit list."),
            small,
        ),
    ]

    doc.build(story)
    return buf.getvalue()
