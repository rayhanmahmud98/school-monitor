"""Student-facing PDFs: ID cards.

A4 sheet = 210 x 297 mm. Each ID card is 85 x 55 mm (credit-card size).
Two cards per A4 sheet, side by side near the top.
"""
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

INDIGO = colors.HexColor("#4338ca")
LIGHT = colors.HexColor("#eef2ff")
SLATE = colors.HexColor("#475569")

CARD_W = 85 * mm
CARD_H = 55 * mm
PHOTO_W = 24 * mm
PHOTO_H = 30 * mm


def _safe(text):
    """Escape and strip anything non-ASCII so ReportLab always renders."""
    if text is None:
        return "-"
    s = str(text)
    return s.encode("ascii", "replace").decode("ascii")


def _photo_flowable(student, w=PHOTO_W, h=PHOTO_H):
    """Return an Image flowable sized to fit w x h, or a placeholder Paragraph."""
    if student.photo and getattr(student.photo, "path", None):
        try:
            return Image(student.photo.path, width=w, height=h)
        except Exception:
            pass
    styles = getSampleStyleSheet()
    placeholder = ParagraphStyle(
        "ph", parent=styles["BodyText"], alignment=1, fontSize=8, textColor=SLATE,
    )
    return Paragraph(
        '<para align="center"><br/><br/>NO<br/>PHOTO</para>',
        placeholder,
    )


def _one_card(student):
    """Build a Table that renders one ID card."""
    school = Paragraph(
        '<font size="11" color="#4338ca"><b>SCHOOL MONITOR</b></font>',
        getSampleStyleSheet()["BodyText"],
    )

    meta_style = ParagraphStyle(
        "meta", parent=getSampleStyleSheet()["BodyText"],
        fontSize=8, leading=11, textColor=SLATE,
    )

    details = (
        "<b>" + _safe(student.full_name) + "</b><br/>"
        "ID: " + _safe(student.student_id) + "<br/>"
        "Class: " + _safe(str(student.class_ref)) + " | Roll " + _safe(student.roll_no) + "<br/>"
        "Blood: " + _safe(student.blood_group) + "<br/>"
        "Guardian: " + _safe(student.guardian_name)
    )

    photo = _photo_flowable(student)
    details_para = Paragraph(details, meta_style)

    inner = Table(
        [[photo, details_para]],
        colWidths=[PHOTO_W + 2 * mm, CARD_W - PHOTO_W - 6 * mm],
    )
    inner.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    outer = Table(
        [[school], [inner]],
        colWidths=[CARD_W],
        rowHeights=[8 * mm, CARD_H - 8 * mm],
    )
    outer.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, INDIGO),
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT),
        ("BACKGROUND", (0, 1), (-1, 1), colors.white),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return outer


def render_id_cards_pdf(students):
    """Return PDF bytes for a list of students, two ID cards per A4 page."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title="Student ID cards",
    )

    story = []
    gap = 5 * mm

    for i in range(0, len(students), 2):
        chunk = students[i:i + 2]
        cards = [_one_card(s) for s in chunk]

        if len(cards) == 1:
            row = [[cards[0], ""]]
            widths = [CARD_W, CARD_W]
            style = TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ])
        else:
            row = [[cards[0], cards[1]]]
            widths = [CARD_W, CARD_W]
            style = TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), gap),
                ("LEFTPADDING", (1, 0), (1, 0), 0),
                ("RIGHTPADDING", (1, 0), (1, 0), 0),
            ])

        t = Table(row, colWidths=widths, rowHeights=[CARD_H])
        t.setStyle(style)
        story.append(t)
        story.append(Spacer(1, 8 * mm))

    if not story:
        story.append(Paragraph("No students to render.", getSampleStyleSheet()["BodyText"]))

    doc.build(story)
    return buf.getvalue()



def render_transfer_certificate_pdf(tc, requested_by=None):
    """Return PDF bytes for a Transfer Certificate."""
    from django.utils import timezone as _tz
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

    student = tc.student

    def safe(v):
        if v is None:
            return "-"
        return str(v).encode("ascii", "replace").decode("ascii")

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"Transfer Certificate - {student.full_name}",
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1tc", parent=styles["Title"], textColor=INDIGO, fontSize=20)
    sub = ParagraphStyle("subtc", parent=styles["Heading3"], alignment=1, textColor=SLATE)
    small = ParagraphStyle("smalltc", parent=styles["BodyText"], fontSize=9, textColor=SLATE)
    body = ParagraphStyle("bodytc", parent=styles["BodyText"], fontSize=11, leading=16)

    story = [
        Paragraph("School Monitoring System", h1),
        Paragraph("Transfer Certificate", sub),
        Spacer(1, 4 * mm),
    ]

    # TC number banner
    num = Table(
        [["Certificate No.", safe(tc.tc_number)],
         ["Date of issue", safe(tc.issued_at.strftime("%d %b %Y"))]],
        colWidths=[45 * mm, 110 * mm],
    )
    num.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [num, Spacer(1, 8 * mm)]

    # Student details
    rows = [
        ["Student name", safe(student.full_name)],
        ["Student ID", safe(student.student_id)],
        ["Class & roll", safe(f"{student.class_ref}  |  Roll {student.roll_no}")],
        ["Date of birth", safe(student.date_of_birth.strftime("%d %b %Y") if student.date_of_birth else None)],
        ["Gender", safe(student.get_gender_display() if student.gender else None)],
        ["Guardian", safe(student.guardian_name)],
        ["Date of admission", safe(student.admission_date.strftime("%d %b %Y") if student.admission_date else None)],
        ["Date of leaving", safe(tc.date_of_leaving.strftime("%d %b %Y"))],
        ["Conduct", safe(tc.conduct)],
        ["Dues cleared", "Yes" if tc.dues_cleared else "No"],
        ["Reason for leaving", safe(tc.get_reason_display() + (f" - {tc.reason_note}" if tc.reason_note else ""))],
    ]
    body_tbl = Table(
        [[Paragraph(k, small), Paragraph(v, body)] for k, v in rows],
        colWidths=[45 * mm, 110 * mm],
    )
    body_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.lightgrey),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [body_tbl, Spacer(1, 6 * mm)]

    # Remarks
    if tc.remarks:
        story += [
            Paragraph("Remarks", styles["Heading4"]),
            Paragraph(safe(tc.remarks), body),
            Spacer(1, 6 * mm),
        ]

    # Declaration
    story += [
        Paragraph(
            "This is to certify that the above student has been a bona fide student of this "
            "institution and has fulfilled all requirements for withdrawal. This certificate "
            "is issued on the request of the parent/guardian.",
            small,
        ),
        Spacer(1, 20 * mm),
    ]

    # Signature block
    sig = Table(
        [["_________________________", "", "_________________________"],
         ["Class teacher", "", "Principal"]],
        colWidths=[60 * mm, 30 * mm, 60 * mm],
    )
    sig.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), SLATE),
        ("TOPPADDING", (0, 0), (-1, 0), 0),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 0),
    ]))
    story += [sig, Spacer(1, 8 * mm)]

    # Footer
    generated = _tz.localtime().strftime("%d %b %Y %H:%M")
    by = safe(requested_by.display_name) if requested_by else "system"
    story += [
        Paragraph(
            safe(f"Generated by {by} on {generated}. "
                 "This is a computer-generated certificate."),
            small,
        ),
    ]

    doc.build(story)
    return buf.getvalue()
