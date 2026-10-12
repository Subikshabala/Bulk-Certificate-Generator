import pytest
from pathlib import Path

from app import config
from app.models import Certificate
from app.services.generator import generate_certificate_pdf
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