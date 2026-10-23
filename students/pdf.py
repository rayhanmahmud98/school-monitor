"""Student-facing PDFs: ID cards and Transfer Certificates."""
from io import BytesIO
import qrcode
from django.urls import reverse

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, PageBreak
)

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


def _qr_flowable(url, size=30*mm):
    img = qrcode.make(url)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Image(buf, width=size, height=size)


def _school_header(profile):
    if profile and profile.logo and getattr(profile.logo, "path", None):
        try:
            logo = Image(profile.logo.path, width=12*mm, height=12*mm)
        except Exception:
            logo = ""
    else:
        logo = ""
    
    name = _safe(profile.name if profile else "SCHOOL MONITOR")
    sub = "OFFICIAL STUDENT IDENTITY CARD"
    
    header_left = Table([[logo, name]], colWidths=[16*mm, 69*mm])
    header_left.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("FONTNAME", (1,0), (1,0), "Helvetica-Bold"),
        ("FONTSIZE", (1,0), (1,0), 12),
        ("TEXTCOLOR", (1,0), (1,0), INDIGO),
    ]))
    
    return [
        header_left,
        Spacer(1, 1*mm),
        Paragraph(f'<font size="8" color="#475569">{sub}</font>', getSampleStyleSheet()["BodyText"]),
        Spacer(1, 4*mm),
        Table([[""]], colWidths=[85*mm], style=[("LINEBELOW", (0,0), (-1,-1), 0.5, colors.lightgrey)]),
        Spacer(1, 4*mm)
    ]


def render_id_cards_pdf(students, request=None, profile=None):
    """Render 1 student per A4 page (Front top half, Back bottom half)."""
    from academics.models import IDCard
    
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, 
        leftMargin=15*mm, rightMargin=15*mm, 
        topMargin=15*mm, bottomMargin=15*mm, 
        title="Student ID Cards"
    )
    
    story = []
    base_url = request.build_absolute_uri("/")[:-1] if request else "http://localhost:8000"

    for student in students:
        card_obj, _ = IDCard.objects.get_or_create(kind=IDCard.Kind.STUDENT, student=student)
        verify_url = f"{base_url}{reverse('dashboard:verify_id_card', args=[str(card_obj.uuid)])}"

        # --- FRONT ---
        front_story = _school_header(profile)
        
        photo = _photo_flowable(student)
        
        info_data = [
            [Paragraph(f'<b>{_safe(student.full_name)}</b>', getSampleStyleSheet()["Heading3"])],
            [Paragraph(f'Class / Grade: {_safe(student.class_ref.name)}', getSampleStyleSheet()["BodyText"])],
            [Paragraph(f'Roll / Adm No: {_safe(student.roll_no)}', getSampleStyleSheet()["BodyText"])],
            [Paragraph(f'Date of Birth: {_safe(student.date_of_birth.strftime("%d %b %Y") if student.date_of_birth else "-")}', getSampleStyleSheet()["BodyText"])],
            [Paragraph(f'Blood Group: {_safe(student.blood_group)}', getSampleStyleSheet()["BodyText"])],
        ]
        info_tbl = Table(info_data, colWidths=[55*mm])
        info_tbl.setStyle(TableStyle([("LEFTPADDING", (0,0), (-1,-1), 0), ("BOTTOMPADDING", (0,0), (-1,-1), 2)]))

        body = Table([[photo, info_tbl]], colWidths=[30*mm, 55*mm])
        body.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP")]))
        front_story.append(body)
        front_story.append(Spacer(1, 4*mm))
        
        front_story.append(Table([[""]], colWidths=[85*mm], style=[("LINEBELOW", (0,0), (-1,-1), 0.5, colors.lightgrey)]))
        front_story.append(Spacer(1, 2*mm))
        
        guardian = Paragraph(f"Parent / Guardian: {_safe(student.guardian_name)}", getSampleStyleSheet()["BodyText"])
        sign = Paragraph("Principal's Signature: ______________________", getSampleStyleSheet()["BodyText"])
        sid = Paragraph(f"STUDENT ID: <b>{_safe(student.student_id)}</b>", getSampleStyleSheet()["BodyText"])
        
        front_story.append(guardian)
        front_story.append(Spacer(1, 6*mm))
        
        footer_tbl = Table([[sign, sid]], colWidths=[55*mm, 30*mm])
        footer_tbl.setStyle(TableStyle([("ALIGN", (1,0), (1,0), "RIGHT")]))
        front_story.append(footer_tbl)

        front_card = Table([[front_story]], colWidths=[85*mm])
        front_card.setStyle(TableStyle([
            ("BOX", (0,0), (-1,-1), 1, INDIGO),
            ("LEFTPADDING", (0,0), (-1,-1), 4*mm),
            ("RIGHTPADDING", (0,0), (-1,-1), 4*mm),
            ("TOPPADDING", (0,0), (-1,-1), 4*mm),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4*mm),
        ]))

        # --- BACK ---
        back_story = [
            Paragraph("<font color='#4338ca'><b>STUDENT ID VERIFICATION</b></font>", 
                      ParagraphStyle("center", parent=getSampleStyleSheet()["Heading3"], alignment=1)),
            Spacer(1, 6*mm),
            _qr_flowable(verify_url, size=35*mm),
            Spacer(1, 4*mm),
            Paragraph("Scan to verify this student's identity", 
                      ParagraphStyle("center2", parent=getSampleStyleSheet()["BodyText"], alignment=1)),
            Spacer(1, 8*mm),
            Table([[""]], colWidths=[85*mm], style=[("LINEBELOW", (0,0), (-1,-1), 0.5, colors.lightgrey)]),
            Spacer(1, 4*mm),
            Paragraph(f"<font size='7' color='#64748b'>{_safe(profile.return_note if profile else 'If found, return to the school office.')}</font>", 
                      ParagraphStyle("center3", parent=getSampleStyleSheet()["BodyText"], alignment=1)),
        ]

        back_card = Table([[back_story]], colWidths=[85*mm], rowHeights=[85*mm])
        back_card.setStyle(TableStyle([
            ("BOX", (0,0), (-1,-1), 1, INDIGO),
            ("ALIGN", (0,0), (-1,-1), "CENTER"),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("TOPPADDING", (0,0), (-1,-1), 6*mm),
        ]))

        # Add to main story
        story.append(front_card)
        story.append(Spacer(1, 8*mm))
        story.append(Paragraph("✂ - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -", 
                               ParagraphStyle("cut", alignment=1, textColor=colors.lightgrey)))
        story.append(Spacer(1, 8*mm))
        story.append(back_card)
        story.append(PageBreak())

    doc.build(story)
    return buf.getvalue()


def render_transfer_certificate_pdf(tc, requested_by=None):
    """Return PDF bytes for a Transfer Certificate."""
    from django.utils import timezone as _tz

    student = tc.student

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
        [["Certificate No.", _safe(tc.tc_number)],
         ["Date of issue", _safe(tc.issued_at.strftime("%d %b %Y"))]],
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
        ["Student name", _safe(student.full_name)],
        ["Student ID", _safe(student.student_id)],
        ["Class & roll", _safe(f"{student.class_ref}  |  Roll {student.roll_no}")],
        ["Date of birth", _safe(student.date_of_birth.strftime("%d %b %Y") if student.date_of_birth else None)],
        ["Gender", _safe(student.get_gender_display() if student.gender else None)],
        ["Guardian", _safe(student.guardian_name)],
        ["Date of admission", _safe(student.admission_date.strftime("%d %b %Y") if student.admission_date else None)],
        ["Date of leaving", _safe(tc.date_of_leaving.strftime("%d %b %Y"))],
        ["Conduct", _safe(tc.conduct)],
        ["Dues cleared", "Yes" if tc.dues_cleared else "No"],
        ["Reason for leaving", _safe(tc.get_reason_display() + (f" - {tc.reason_note}" if tc.reason_note else ""))],
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
            Paragraph(_safe(tc.remarks), body),
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
    by = _safe(requested_by.display_name) if requested_by else "system"
    story += [
        Paragraph(
            _safe(f"Generated by {by} on {generated}. "
                 "This is a computer-generated certificate."),
            small,
        ),
    ]

    doc.build(story)
    return buf.getvalue()