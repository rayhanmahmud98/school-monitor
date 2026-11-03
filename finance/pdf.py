"""Finance PDF generation — dual-copy A4 payment receipts."""
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

# ---- font registration (Bangla if available, Helvetica otherwise) ----------------------

_BANGLA_FONT_PATH = Path(__file__).resolve().parent.parent / "static" / "fonts" / "NotoSansBengali-Regular.ttf"
_BANGLA_FONT_NAME = "Helvetica"  # fallback

if _BANGLA_FONT_PATH.exists():
    try:
        pdfmetrics.registerFont(TTFont("NotoSansBengali", str(_BANGLA_FONT_PATH)))
        _BANGLA_FONT_NAME = "NotoSansBengali"
    except Exception:
        # If registration fails for any reason, fall back to Helvetica so the PDF still builds.
        _BANGLA_FONT_NAME = "Helvetica"


def _safe(value) -> str:
    """Return a printable string; keep Unicode so Bangla can render if the font supports it.

    ReportLab's Helvetica drops non-ASCII glyphs, but the NotoSansBengali TTF (when
    registered) preserves them. We do not strip; we only guard against None.
    """
    if value is None or value == "":
        return "-"
    return str(value)


def _money(value) -> str:
    try:
        return f"{value:,.2f}"
    except Exception:
        return str(value)


# ---- receipt layout --------------------------------------------------------------------

INDIGO = colors.HexColor("#4338ca")
SLATE = colors.HexColor("#475569")
LIGHT_BORDER = colors.HexColor("#e2e8f0")
HIGHLIGHT = colors.HexColor("#eef2ff")


def _styles():
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title", parent=styles["Title"], fontSize=15, leading=18,
            textColor=INDIGO, alignment=1, fontName=_BANGLA_FONT_NAME,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=styles["Normal"], fontSize=8, leading=10,
            textColor=SLATE, alignment=1, fontName=_BANGLA_FONT_NAME,
        ),
        "label": ParagraphStyle(
            "label", parent=styles["Normal"], fontSize=8, leading=10,
            textColor=SLATE, fontName=_BANGLA_FONT_NAME,
        ),
        "value": ParagraphStyle(
            "value", parent=styles["Normal"], fontSize=9, leading=11,
            textColor=colors.black, fontName=_BANGLA_FONT_NAME,
        ),
        "big": ParagraphStyle(
            "big", parent=styles["Normal"], fontSize=12, leading=14,
            textColor=colors.black, fontName=_BANGLA_FONT_NAME,
        ),
        "small": ParagraphStyle(
            "small", parent=styles["Normal"], fontSize=7, leading=9,
            textColor=SLATE, fontName=_BANGLA_FONT_NAME,
        ),
    }


def _one_copy(receipt, styles, copy_label: str):
    """Return the list of flowables for a single copy of the receipt."""
    student = receipt.student
    inv = receipt.invoice  # may be None for a general (unapplied) payment

    header = [
        Paragraph("School Monitor", styles["title"]),
        Paragraph(f"Payment Receipt — {copy_label}", styles["subtitle"]),
        Spacer(1, 3 * mm),
    ]

    # Rows for the meta table. Show invoice rows only when an invoice is linked;
    # otherwise show "Unapplied credit" so the receipt is self-describing.
    rows = [
        ["Receipt No.", _safe(receipt.number)],
        ["Date", _safe((receipt.payment_date or receipt.received_at).strftime("%d %b %Y"))],
        ["Student", _safe(student.full_name if student else "-")],
        ["Student ID", _safe(student.student_id if student else "-")],
        ["Class", _safe(str(student.class_ref) if student and student.class_ref else "-")],
        ["Method", _safe(receipt.get_method_display())],
    ]
    if receipt.reference:
        rows.append(["Reference", _safe(receipt.reference)])
    if receipt.bank_name:
        rows.append(["Bank", _safe(receipt.bank_name)])
    if receipt.branch_name:
        rows.append(["Branch", _safe(receipt.branch_name)])
    if receipt.cheque_date:
        rows.append(["Cheque date", _safe(receipt.cheque_date.strftime("%d %b %Y"))])
    if inv is not None:
        rows.append(["Invoice", _safe(inv.invoice_no)])
        rows.append(["Fee category", _safe(inv.fee_category.name if inv.fee_category else "-")])
    else:
        rows.append(["Applied to", "Unapplied credit"])

    meta = Table(
        [[Paragraph(k, styles["label"]), Paragraph(v, styles["value"])] for k, v in rows],
        colWidths=[32 * mm, 100 * mm],
    )
    meta.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, LIGHT_BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))

    amounts = [
        ["Amount received", _money(receipt.amount)],
    ]
    if inv is not None:
        amounts.append(["Invoice total", _money(inv.net_payable)])
        amounts.append(["Invoice balance", _money(inv.balance)])
    amounts_tbl = Table(
        [[Paragraph(k, styles["label"]), Paragraph(v, styles["big"])] for k, v in amounts],
        colWidths=[90 * mm, 42 * mm],
    )
    amounts_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, LIGHT_BORDER),
        ("BACKGROUND", (0, -1), (-1, -1), HIGHLIGHT),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    footer = [
        Spacer(1, 5 * mm),
        Table(
            [[
                Paragraph("Received by: __________________________", styles["small"]),
                Paragraph("Authorised by: __________________________", styles["small"]),
            ]],
            colWidths=[66 * mm, 66 * mm],
        ),
        Spacer(1, 2 * mm),
        Paragraph(
            _safe(f"Received by: {receipt.received_by.display_name if receipt.received_by else '-'} "
                  f"· Generated on {receipt.created_at.strftime('%d %b %Y %H:%M')}"),
            styles["small"],
        ),
    ]

    return header + [meta, Spacer(1, 3 * mm), amounts_tbl] + footer


def _cut_line():
    return [
        Spacer(1, 3 * mm),
        Table(
            [[
                Paragraph("&nbsp;" * 1, getSampleStyleSheet()["Normal"]),
                Paragraph("✂", ParagraphStyle(
                    "scissors", fontSize=10, textColor=SLATE, alignment=1,
                )),
                Paragraph("&nbsp;" * 1, getSampleStyleSheet()["Normal"]),
            ]],
            colWidths=[60 * mm, 20 * mm, 60 * mm],
            style=TableStyle([
                ("LINEBELOW", (0, 0), (0, 0), 0.5, SLATE),
                ("LINEBELOW", (2, 0), (2, 0), 0.5, SLATE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]),
        ),
        Spacer(1, 3 * mm),
    ]


def render_receipt_pdf(receipt, requested_by=None):
    """Render one A4 portrait page with School Copy (top) and Student Copy (bottom).

    Both copies come from the same PaymentReceipt instance, so they always match.
    Reprinting calls this function again — it never creates a new receipt.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
        title=f"Receipt {receipt.number}",
    )
    styles = _styles()
    story = []
    story += _one_copy(receipt, styles, "School Copy")
    story += _cut_line()
    story += _one_copy(receipt, styles, "Student Copy")
    doc.build(story)
    return buf.getvalue()