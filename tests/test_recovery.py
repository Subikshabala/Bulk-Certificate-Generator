from datetime import date
from threading import Event

from app import main
from app.models import Certificate, Job


def test_startup_recovers_pending_rows_only_for_unfinished_jobs(test_environment):
    _, sessions = test_environment
    with sessions() as db:
        unfinished = Job(
            status="PROCESSING",
            event_name="Recovery workshop",
            issuer_name="Academy",
            issue_date=date(2026, 10, 12),
            total_count=2,
        )
        completed = Job(
            status="COMPLETED",
            event_name="Finished workshop",
            issuer_name="Academy",
            issue_date=date(2026, 10, 12),
            total_count=1,
            success_count=1,
        )
        db.add_all([unfinished, completed])
        db.flush()
        db.add_all(
            [
                Certificate(
                    job_id=unfinished.id,
                    recipient_name="Pending",
                    recipient_email="pending@example.com",
                    status="PENDING",
                ),
                Certificate(
                    job_id=unfinished.id,
                    recipient_name="Already failed",
                    recipient_email="failed@example.com",
                    status="FAILED",
                    error_message="Previous failure",
                ),
                Certificate(
                    job_id=completed.id,
                    recipient_name="Do not resume",
                    recipient_email="done@example.com",
                    status="PENDING",
                ),
            ]
        )
        db.commit()
        unfinished_id = unfinished.id
        completed_id = completed.id

    main.initialize_database_and_recover_jobs()

    with sessions() as db:
        unfinished = db.get(Job, unfinished_id)
        completed = db.get(Job, completed_id)
        rows = db.query(Certificate).filter(Certificate.job_id == unfinished_id).all()
        completed_row = db.query(Certificate).filter(Certificate.job_id == completed_id).one()
        assert unfinished.status == "COMPLETED_WITH_ERRORS"
        assert unfinished.success_count == 1 and unfinished.failed_count == 1
        assert sorted(row.status for row in rows) == ["FAILED", "SUCCESS"]
        assert completed.status == "COMPLETED" and completed_row.status == "PENDING"


def test_recovery_thread_is_daemon(monkeypatch):
    finished = Event()
    monkeypatch.setattr(main, "recover_unfinished_jobs", finished.set)

    thread = main.start_recovery_thread()

    assert thread.daemon
    assert finished.wait(timeout=2)
    thread.join()