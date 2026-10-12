import pytest
from pathlib import Path
from reportlab.pdfbase.ttfonts import TTFont

from app import config
from app.models import Certificate
from app.services.generator import FONT_PATHS, _font_name, generate_certificate_pdf
from app.services.processor import process_job


def test_processing_writes_pdf_files(test_environment):
    client, sessions = test_environment
    response = client.post("/api/v1/jobs", json={
        "event_name": "Workshop", "issuer_name": "Academy", "issue_date": "2026-10-12",
        "recipients": [{"name": "Αθηνά <Research & Design>", "email": "athina@example.com"}],
    })
    process_job(response.json()["job_id"])
    with sessions() as db:
        certificate = db.query(Certificate).one()
        content = Path(certificate.file_path).read_bytes()
        assert certificate.status == "SUCCESS"
        assert content.startswith(b"%PDF") and len(content) > 100
        assert b"/FontFile2" in content


def test_generator_rejects_path_outside_storage(test_environment, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CERT_STORAGE_DIR", tmp_path / "certificates")
    with pytest.raises(ValueError, match="inside CERT_STORAGE_DIR"):
        generate_certificate_pdf({}, tmp_path / "outside.pdf")


def test_long_name_generates_a_pdf(test_environment):
    output_path = config.CERT_STORAGE_DIR / "job-id" / "certificate-id.pdf"
    generate_certificate_pdf(
        {"recipient_name": "Long Name " * 10, "event_name": "Workshop"},
        output_path,
    )
    assert output_path.read_bytes().startswith(b"%PDF")


@pytest.mark.parametrize(
    ("name", "expected_font"),
    [
        ("பாலாஜி", "NotoSansTamil"),
        ("கொடி சென்னை", "NotoSansTamil"),
        ("Αλέξης", "NotoSans"),
        ("Иван", "NotoSans"),
        ("José Álvarez", "NotoSans"),
    ],
)
def test_unicode_names_generate_pdfs_and_select_font(test_environment, name, expected_font):
    output_path = config.CERT_STORAGE_DIR / "unicode-job" / f"{len(name)}.pdf"
    generate_certificate_pdf(
        {"recipient_name": name, "event_name": "Workshop", "issuer_name": "Academy"},
        output_path,
    )
    assert output_path.read_bytes().startswith(b"%PDF")
    assert _font_name(name) == expected_font


@pytest.mark.parametrize(
    ("name", "font_key"),
    [
        ("பாலாஜி", "NotoSansTamil"),
        ("Αλέξης", "NotoSans"),
        ("Иван", "NotoSans"),
        ("José Álvarez", "NotoSans"),
    ],
)
def test_selected_font_contains_every_name_character(name, font_key):
    assert FONT_PATHS[font_key].is_file()
    assert _font_name(name) == font_key
    font = TTFont(font_key, str(FONT_PATHS[font_key]))
    character_map = font.face.charWidths
    assert all(ord(character) in character_map for character in name)