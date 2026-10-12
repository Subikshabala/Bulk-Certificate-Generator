"""Render a fixed landscape A4 certificate template."""

from pathlib import Path
import re
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

FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"
FONT_PATHS = {
    "NotoSans": FONT_DIR / "NotoSans-Regular.ttf",
    "NotoSansTamil": FONT_DIR / "NotoSansTamil-Regular.ttf",
    "CertificateVera": FONT_DIR / "Vera.ttf",
}
_FONT_LOCK = Lock()
_REGISTERED_FONTS: set[str] = set()
_FONTS_INITIALIZED = False


def _register_fonts() -> None:
    """Register each available bundled font once, safely across worker threads."""
    global _FONTS_INITIALIZED
    if _FONTS_INITIALIZED:
        return
    with _FONT_LOCK:
        if _FONTS_INITIALIZED:
            return
        for name, path in FONT_PATHS.items():
            if path.is_file():
                try:
                    pdfmetrics.registerFont(TTFont(name, str(path)))
                    _REGISTERED_FONTS.add(name)
                except Exception:
                    pass
        _FONTS_INITIALIZED = True


def _font_name(text: object) -> str:
    """Choose Tamil or general Unicode fonts, then use local fallbacks."""
    _register_fonts()
    value = str(text)
    preferred = "NotoSansTamil" if any("\u0b80" <= char <= "\u0bff" for char in value) else "NotoSans"
    for name in (preferred, "NotoSans", "CertificateVera"):
        if name in _REGISTERED_FONTS:
            return name
    return "Helvetica"


def _font_runs(text: object) -> list[tuple[str, str]]:
    """Split on whitespace; return (token, font_name) pairs using _font_name."""
    return [(token, _font_name(token)) for token in re.split(r"(\s+)", str(text)) if token]


def _normalize_windows_path(value: str) -> str:
    """Remove Windows extended-length prefixes for consistent path comparison."""
    if value.startswith("\\\\?\\UNC\\"):
        return "\\\\" + value[8:]
    if value.startswith("\\\\?\\"):
        return value[4:]
    return value


def _resolved_path(path: Path) -> Path:
    """Resolve a path and normalize Windows extended-length path prefixes."""
    return Path(_normalize_windows_path(str(path.resolve())))


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
    auto_font: bool = True,
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
            shaping=True,
        )
        if auto_font:
            paragraph_text = "".join(
                f'<font name="{font}">{escape(token)}</font>'
                for token, font in _font_runs(text)
            )
        else:
            paragraph_text = escape(str(text))
        paragraph = Paragraph(paragraph_text, style)
        _, height = paragraph.wrap(width, 1000)
        if not shrink or height <= size * 1.3 or size == minimum_size:
            paragraph.drawOn(pdf, center_x - width / 2, top_y - height)
            return


def generate_certificate_pdf(data: dict, output_path: Path) -> Path:
    """Generate a printable certificate under CERT_STORAGE_DIR."""
    storage_root = _resolved_path(config.CERT_STORAGE_DIR)
    output_path = _resolved_path(output_path)
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
    _draw_paragraph(pdf, "Certificate of Completion", center, page_height - 78, page_width - 100,
                    "Helvetica-Bold", 28, dark_green, auto_font=False)
    _draw_paragraph(pdf, "This is to certify that", center, page_height - 128, page_width - 100,
                    _font_name("This is to certify that"), 13, charcoal)
    _draw_paragraph(pdf, data.get("recipient_name", ""), center, page_height - 168, page_width - 120,
                    _font_name(data.get("recipient_name", "")), 34, dark_green, shrink=True)
    _draw_paragraph(pdf, "has successfully completed", center, page_height - 230, page_width - 100,
                    _font_name("has successfully completed"), 13, charcoal)

    event_name = data.get("event_name", "")
    _draw_paragraph(pdf, event_name, center, page_height - 260, page_width - 100,
                    _font_name(event_name), 20, dark_green)
    course = data.get("course")
    if course:
        _draw_paragraph(pdf, course, center, page_height - 290, page_width - 100,
                        _font_name(course), 14, dark_green)
    _draw_paragraph(pdf, f"Issued on {data.get('issue_date', '')}", center, 130,
                    page_width - 100, _font_name("Issued on"), 12, charcoal)
    issuer_name = data.get("issuer_name", "")
    _draw_paragraph(pdf, issuer_name, center, 100,
                    page_width - 100, _font_name(issuer_name), 13, dark_green)
    _draw_paragraph(pdf, f"Certificate ID: {data.get('certificate_id', '')}", center, 68,
                    page_width - 100, _font_name("Certificate ID:"), 8, charcoal)
    pdf.save()
    return output_path