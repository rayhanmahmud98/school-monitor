from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, PageBreak)
from django.urls import reverse
import qrcode

INDIGO = colors.HexColor("#4338ca")

def _safe(text):
    """Strip non-ASCII for ReportLab."""
    if text is None: 
        return "-"
    return str(text).encode("ascii", "replace").decode("ascii")

def _qr_flowable(url, size=30*mm):
    img = qrcode.make(url)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Image(buf, width=size, height=size)

def render_teacher_id_cards_pdf(teachers, request=None, profile=None):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15*mm, rightMargin=15*mm, topMargin=15*mm, bottomMargin=15*mm)
    
    from academics.models import IDCard
    story = []
    base_url = request.build_absolute_uri("/")[:-1] if request else "http://localhost:8000"

    for teacher in teachers:
        card_obj, _ = IDCard.objects.get_or_create(kind=IDCard.Kind.TEACHER, teacher=teacher)
        verify_url = f"{base_url}{reverse('dashboard:verify_id_card', args=[str(card_obj.uuid)])}"
        
        prof = getattr(teacher, "teacher_profile", None)
        photo = ""
        if prof and prof.photo and getattr(prof.photo, "path", None):
            try:
                photo = Image(prof.photo.path, width=24*mm, height=30*mm)
            except Exception:
                pass
        
        if not photo:
            photo = Paragraph('<para align="center"><br/><br/>NO<br/>PHOTO</para>', getSampleStyleSheet()["BodyText"])

        # Front
        front_story = [
            Paragraph(f"<font color='#4338ca'><b>{_safe(profile.name if profile else 'SCHOOL MONITOR')}</b></font>", getSampleStyleSheet()["Heading3"]),
            Paragraph("OFFICIAL TEACHER IDENTITY CARD", getSampleStyleSheet()["BodyText"]),
            Spacer(1, 4*mm),
            Table([[""]], colWidths=[85*mm], style=[("LINEBELOW", (0,0), (-1,-1), 0.5, colors.lightgrey)]),
            Spacer(1, 4*mm)
        ]
        
        info_data = [
            [Paragraph(f'<b>{_safe(teacher.display_name)}</b>', getSampleStyleSheet()["Heading3"])],
            [Paragraph(f'Designation: {_safe(prof.designation if prof else "-")}', getSampleStyleSheet()["BodyText"])],
            [Paragraph(f'Department: {_safe(prof.subject_specialization if prof else "-")}', getSampleStyleSheet()["BodyText"])],
            [Paragraph(f'Employee ID: {_safe(prof.employee_id if prof else "-")}', getSampleStyleSheet()["BodyText"])],
        ]
        info_tbl = Table(info_data, colWidths=[55*mm])
        info_tbl.setStyle(TableStyle([("LEFTPADDING", (0,0), (-1,-1), 0), ("BOTTOMPADDING", (0,0), (-1,-1), 2)]))

        body = Table([[photo, info_tbl]], colWidths=[30*mm, 55*mm])
        body.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP")]))
        front_story.append(body)
        front_story.append(Spacer(1, 4*mm))
        
        front_story.append(Table([[""]], colWidths=[85*mm], style=[("LINEBELOW", (0,0), (-1,-1), 0.5, colors.lightgrey)]))
        front_story.append(Spacer(1, 6*mm))
        
        sign = Paragraph("Principal's Signature: ______________________", getSampleStyleSheet()["BodyText"])
        footer_tbl = Table([[sign, ""]], colWidths=[55*mm, 30*mm])
        front_story.append(footer_tbl)

        front_card = Table([[front_story]], colWidths=[85*mm])
        front_card.setStyle(TableStyle([("BOX", (0,0), (-1,-1), 1, INDIGO), ("LEFTPADDING", (0,0), (-1,-1), 4*mm), ("RIGHTPADDING", (0,0), (-1,-1), 4*mm), ("TOPPADDING", (0,0), (-1,-1), 4*mm), ("BOTTOMPADDING", (0,0), (-1,-1), 4*mm)]))

        # Back
        back_story = [
            Paragraph("<font color='#4338ca'><b>TEACHER ID VERIFICATION</b></font>", ParagraphStyle("center", parent=getSampleStyleSheet()["Heading3"], alignment=1)),
            Spacer(1, 6*mm),
            _qr_flowable(verify_url, size=35*mm),
            Spacer(1, 4*mm),
            Paragraph("Scan to verify this teacher's identity", ParagraphStyle("center2", parent=getSampleStyleSheet()["BodyText"], alignment=1)),
            Spacer(1, 8*mm),
            Table([[""]], colWidths=[85*mm], style=[("LINEBELOW", (0,0), (-1,-1), 0.5, colors.lightgrey)]),
            Spacer(1, 4*mm),
            Paragraph(f"<font size='7' color='#64748b'>{_safe(profile.return_note if profile else 'If found, return to the school office.')}</font>", ParagraphStyle("center3", parent=getSampleStyleSheet()["BodyText"], alignment=1)),
        ]
        back_card = Table([[back_story]], colWidths=[85*mm], rowHeights=[85*mm])
        back_card.setStyle(TableStyle([("BOX", (0,0), (-1,-1), 1, INDIGO), ("ALIGN", (0,0), (-1,-1), "CENTER"), ("VALIGN", (0,0), (-1,-1), "TOP"), ("TOPPADDING", (0,0), (-1,-1), 6*mm)]))

        story.extend([front_card, Spacer(1, 8*mm), Paragraph("✂ - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -", ParagraphStyle("cut", alignment=1, textColor=colors.lightgrey)), Spacer(1, 8*mm), back_card, PageBreak()])

    doc.build(story)
    return buf.getvalue()