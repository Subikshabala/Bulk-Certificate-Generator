import io
import zipfile

from app.routers import jobs as jobs_router
from app.services.processor import process_job


def test_downloads_and_certificate_listing(test_environment, monkeypatch):
    client, _ = test_environment
    monkeypatch.setattr(jobs_router, "process_job", lambda job_id: None)
    response = client.post("/api/v1/jobs", json={
        "event_name": "Workshop", "issuer_name": "Academy", "issue_date": "2026-10-12",
        "recipients": [
            {"name": "Asha", "email": "asha@example.com"},
            {"name": "Bo", "email": "bo@example.com"},
            {"name": "Invalid", "email": "not-an-email"},
        ],
    })
    job_id = response.json()["job_id"]
    process_job(job_id)
    listing = client.get(f"/api/v1/jobs/{job_id}/certificates?status=SUCCESS").json()
    assert listing["total_count"] == 2 and len(listing["items"]) == 2
    failed_listing = client.get(f"/api/v1/jobs/{job_id}/certificates?status=FAILED").json()
    assert failed_listing["total_count"] == 1
    page = client.get(
        f"/api/v1/jobs/{job_id}/certificates?status=SUCCESS&limit=1&offset=1"
    ).json()
    assert page["total_count"] == 2 and len(page["items"]) == 1 and page["offset"] == 1
    certificate_id = listing["items"][0]["id"]
    pdf = client.get(f"/api/v1/certificates/{certificate_id}/download")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    archive = client.get(f"/api/v1/jobs/{job_id}/download")
    assert archive.status_code == 200 and archive.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(archive.content)) as zipped:
        assert set(zipped.namelist()) == {f"{item['id']}.pdf" for item in listing["items"]}


def test_download_not_found_or_not_ready(test_environment, monkeypatch):
    client, _ = test_environment
    assert client.get("/api/v1/certificates/missing/download").status_code == 404
    monkeypatch.setattr(jobs_router, "process_job", lambda job_id: None)
    response = client.post("/api/v1/jobs", json={
        "event_name": "Workshop", "issuer_name": "Academy", "issue_date": "2026-10-12",
        "recipients": [{"name": "Asha", "email": "asha@example.com"}],
    })
    job_id = response.json()["job_id"]
    listing = client.get(f"/api/v1/jobs/{job_id}/certificates").json()
    assert client.get(f"/api/v1/certificates/{listing['items'][0]['id']}/download").status_code == 409
    assert client.get(f"/api/v1/jobs/{job_id}/download").status_code == 409