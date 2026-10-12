from app import config
from app.routers import jobs as jobs_router


def payload(recipients=None):
    return {
        "event_name": "Python Workshop 2026",
        "issuer_name": "Tech Academy",
        "issue_date": "2026-10-12",
        "recipients": recipients if recipients is not None else [{"name": "Asha K", "email": "asha@example.com"}],
    }


def test_request_level_validation(test_environment, monkeypatch):
    client, sessions = test_environment
    monkeypatch.setattr(jobs_router, "process_job", lambda job_id: None)
    base = payload()
    for field in ("event_name", "issuer_name", "issue_date", "recipients"):
        incomplete = {key: value for key, value in base.items() if key != field}
        assert client.post("/api/v1/jobs", json=incomplete).status_code == 422
    assert client.post(
        "/api/v1/jobs", content="{broken", headers={"Content-Type": "application/json"}
    ).status_code == 422
    assert client.post("/api/v1/jobs", json=payload([])).status_code == 422
    monkeypatch.setattr(config, "MAX_RECIPIENTS_PER_JOB", 2)
    assert client.post("/api/v1/jobs", json=payload([{}, {}, {}])).status_code == 422
    with sessions() as db:
        from app.models import Job
        assert db.query(Job).count() == 0


def test_invalid_recipients_are_saved_per_item(test_environment, monkeypatch):
    client, sessions = test_environment
    monkeypatch.setattr(jobs_router, "process_job", lambda job_id: None)
    response = client.post(
        "/api/v1/jobs",
        json=payload([
            {"name": " Good ", "email": "Good@Example.COM "},
            {"name": " ", "email": "blank@example.com"},
            {"name": "Bad", "email": "not-an-email"},
            {"name": "Again", "email": "good@example.com"},
            {"name": "N" * 101, "email": "long@example.com"},
        ]),
    )
    assert response.status_code == 202
    with sessions() as db:
        from app.models import Certificate
        rows = db.query(Certificate).order_by(Certificate.created_at, Certificate.id).all()
        assert len(rows) == 5
        assert sum(row.status == "FAILED" for row in rows) == 4
        assert all(row.error_message for row in rows if row.status == "FAILED")
        good_rows = [row for row in rows if row.recipient_email == "good@example.com"]
        assert len(good_rows) == 2
        assert sum(row.status == "PENDING" for row in good_rows) == 1
        assert any(row.recipient_name == "Good" for row in good_rows)
        assert any(
            row.status == "FAILED" and "Duplicate email" in row.error_message
            for row in good_rows
        )
        long_name = db.query(Certificate).filter(Certificate.recipient_email == "long@example.com").one()
        assert len(long_name.recipient_name) == 100
        assert "at most 100" in long_name.error_message


def test_all_invalid_recipients_fail_job_immediately(test_environment, monkeypatch):
    client, sessions = test_environment
    monkeypatch.setattr(jobs_router, "process_job", lambda job_id: None)
    response = client.post("/api/v1/jobs", json=payload([{"name": " ", "email": "bad"}]))
    assert response.status_code == 202
    assert response.json()["status"] == "FAILED"
    with sessions() as db:
        from app.models import Certificate, Job
        job = db.get(Job, response.json()["job_id"])
        certificate = db.query(Certificate).one()
        assert job.failed_count == 1 and certificate.status == "FAILED"