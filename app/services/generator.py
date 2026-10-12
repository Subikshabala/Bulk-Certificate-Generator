"""Render a fixed landscape A4 certificate template."""

from pathlib import Path
from threading import Lock
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

from app import config

FONT_PATH = Path(__file__).resolve().parents[1] / "assets" / "fonts" / "Vera.ttf"
FONT_NAME = "CertificateUnicode"
_FONT_LOCK = Lock()


def _font_name() -> str:
    """Register the bundled Unicode font, falling back to Helvetica if absent."""
    if FONT_NAME in pdfmetrics.getRegisteredFontNames():
        return FONT_NAME
    with _FONT_LOCK:
        try:
            if FONT_NAME not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(FONT_NAME, str(FONT_PATH)))
            return FONT_NAME
        except Exception:
            return "Helvetica"


def _draw_paragraph(
    pdf: canvas.Canvas,
    text: object,
    center_x: float,
    top_y: float,
    width: float,
    font_name: str,
    font_size: int,
    color: colors.Color,
    shrink: bool = False,
) -> None:
    """Draw XML-escaped text, shrinking it if it wraps beyond one line."""
    minimum_size = 16 if shrink else font_size
    for size in range(font_size, minimum_size - 1, -1):
        style = ParagraphStyle(
            "CertificateText",
            fontName=font_name,
            fontSize=size,
            leading=size * 1.25,
            alignment=TA_CENTER,
            textColor=color,
        )
        paragraph = Paragraph(escape(str(text)), style)
        _, height = paragraph.wrap(width, 1000)
        if not shrink or height <= size * 1.3 or size == minimum_size:
            paragraph.drawOn(pdf, center_x - width / 2, top_y - height)
            return


def generate_certificate_pdf(data: dict, output_path: Path) -> Path:
    """Generate a printable certificate under CERT_STORAGE_DIR."""
    storage_root = config.CERT_STORAGE_DIR.resolve()
    output_path = output_path.resolve()
    if not output_path.is_relative_to(storage_root):
        raise ValueError("Certificate output path must be inside CERT_STORAGE_DIR.")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    page_width, page_height = landscape(A4)
    pdf = canvas.Canvas(str(output_path), pagesize=(page_width, page_height))
    pdf.setStrokeColor(colors.HexColor("#183B35"))
    pdf.setLineWidth(3)
    pdf.rect(28, 28, page_width - 56, page_height - 56)
    pdf.setStrokeColor(colors.HexColor("#B88A45"))
    pdf.setLineWidth(1)
    pdf.rect(36, 36, page_width - 72, page_height - 72)

    center = page_width / 2
    dark_green = colors.HexColor("#183B35")
    charcoal = colors.HexColor("#444444")
    font_name = _font_name()
    _draw_paragraph(pdf, "Certificate of Completion", center, page_height - 78, page_width - 100,
                    "Helvetica-Bold", 28, dark_green)
    _draw_paragraph(pdf, "This is to certify that", center, page_height - 128, page_width - 100,
                    font_name, 13, charcoal)
    _draw_paragraph(pdf, data.get("recipient_name", ""), center, page_height - 168, page_width - 120,
                    font_name, 34, dark_green, shrink=True)
    _draw_paragraph(pdf, "has successfully completed", center, page_height - 230, page_width - 100,
                    font_name, 13, charcoal)

    event_text = str(data.get("event_name", ""))
    if data.get("course"):
        event_text = f"{event_text} - {data['course']}"
    _draw_paragraph(pdf, event_text, center, page_height - 260, page_width - 100,
                    font_name, 20, dark_green)
    _draw_paragraph(pdf, f"Issued on {data.get('issue_date', '')}", center, 130,
                    page_width - 100, font_name, 12, charcoal)
    _draw_paragraph(pdf, data.get("issuer_name", ""), center, 100,
                    page_width - 100, font_name, 13, dark_green)
    _draw_paragraph(pdf, f"Certificate ID: {data.get('certificate_id', '')}", center, 68,
                    page_width - 100, font_name, 8, charcoal)
    pdf.save()
    return output_path