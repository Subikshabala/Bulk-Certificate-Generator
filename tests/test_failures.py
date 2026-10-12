from app.models import Certificate, Job
from app.routers import jobs as jobs_router
from app.services import processor


def test_one_generation_failure_does_not_stop_other_recipients(test_environment, monkeypatch):
    client, sessions = test_environment
    monkeypatch.setattr(jobs_router, "process_job", lambda job_id: None)
    real_generator = processor.generate_certificate_pdf

    def failing_generator(data, output_path):
        if data["recipient_name"] == "Broken":
            raise RuntimeError("render failed")
        return real_generator(data, output_path)

    monkeypatch.setattr(processor, "generate_certificate_pdf", failing_generator)
    response = client.post("/api/v1/jobs", json={
        "event_name": "Workshop", "issuer_name": "Academy", "issue_date": "2026-10-12",
        "recipients": [
            {"name": "Asha", "email": "asha@example.com"},
            {"name": "Broken", "email": "broken@example.com"},
            {"name": "Bo", "email": "bo@example.com"},
        ],
    })
    processor.process_job(response.json()["job_id"])
    with sessions() as db:
        rows = db.query(Certificate).all()
        job = db.get(Job, response.json()["job_id"])
        assert sum(row.status == "SUCCESS" for row in rows) == 2
        failed = next(row for row in rows if row.status == "FAILED")
        assert failed.error_message == "render failed"
        assert job.status == "COMPLETED_WITH_ERRORS"