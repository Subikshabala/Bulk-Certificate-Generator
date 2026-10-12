from app.routers import jobs as jobs_router
from app.models import Job


def test_create_job_returns_202_and_persists_counts(test_environment, monkeypatch):
    client, sessions = test_environment
    assert client.get("/health").status_code == 200
    assert client.get("/health").json() == {"status": "ok"}
    monkeypatch.setattr(jobs_router, "process_job", lambda job_id: None)
    response = client.post("/api/v1/jobs", json={
        "event_name": "Workshop", "issuer_name": "Academy", "issue_date": "2026-10-12",
        "recipients": [{"name": "Asha", "email": "asha@example.com"}, {"name": "Bo", "email": "bo@example.com"}],
    })
    assert response.status_code == 202
    body = response.json()
    assert body["job_id"] and body["status"] == "PENDING" and body["total_count"] == 2
    create_schema = client.get("/openapi.json").json()["components"]["schemas"]["JobCreate"]
    assert create_schema["examples"][0]["event_name"] == "Python Workshop 2026"
    with sessions() as db:
        job = db.get(Job, body["job_id"])
        assert job is not None and job.total_count == 2 and job.failed_count == 0