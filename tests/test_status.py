from app.routers import jobs as jobs_router
from app.services.processor import process_job


def test_status_before_and_after_processing(test_environment, monkeypatch):
    client, sessions = test_environment
    monkeypatch.setattr(jobs_router, "process_job", lambda job_id: None)
    response = client.post("/api/v1/jobs", json={
        "event_name": "Workshop", "issuer_name": "Academy", "issue_date": "2026-10-12",
        "recipients": [
            {"name": "Asha", "email": "asha@example.com"},
            {"name": "Bo", "email": "bo@example.com"},
        ],
    })
    job_id = response.json()["job_id"]
    before = client.get(f"/api/v1/jobs/{job_id}").json()
    assert before["status"] == "PENDING" and before["pending_count"] == 2
    assert before["progress_percent"] == 0
    process_job(job_id)
    after = client.get(
        f"/api/v1/jobs/{job_id}?include_items=true&limit=10"
    ).json()
    assert (
        after["status"] == "COMPLETED" and after["progress_percent"] == 100
    ), [(item["email"], item["error_message"]) for item in after["items"]]
    assert after["success_count"] == 2
    assert all(item["status"] == "SUCCESS" for item in after["items"])
    page = client.get(
        f"/api/v1/jobs/{job_id}?include_items=true&limit=1&offset=1"
    ).json()
    assert len(page["items"]) == 1


def test_unknown_job_is_404(test_environment):
    client, _ = test_environment
    assert client.get("/api/v1/jobs/not-a-job").status_code == 404