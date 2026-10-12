"""Isolated background processing for certificate rows."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select

from app import config
from app.database import SessionLocal
from app.models import Certificate, Job
from app.services.generator import generate_certificate_pdf

# Work starts after the 202 response, so the client does not wait for rendering.
# In-process threads need no Celery/Redis service, unlike a durable queue.
# A stopped process can lose active work; startup retries rows still marked pending.
# Celery/Redis is the next step if durable retries or multiple worker hosts are needed.


@dataclass(frozen=True)
class CertificateResult:
    """Outcome returned by one certificate worker for a batched database write."""

    certificate_id: str
    status: str
    file_path: str | None = None
    error_message: str | None = None


def _process_certificate(certificate_id: str) -> CertificateResult | None:
    """Generate one pending certificate using a worker-owned read session."""
    db = None
    try:
        db = SessionLocal()
        certificate = db.get(Certificate, certificate_id)
        if certificate is None or certificate.status != "PENDING":
            return None
        job = db.get(Job, certificate.job_id)
        if job is None:
            raise ValueError("Parent job was not found.")
        output_path = config.CERT_STORAGE_DIR / job.id / f"{certificate.id}.pdf"
        data = {
            "certificate_id": certificate.id,
            "recipient_name": certificate.recipient_name,
            "event_name": job.event_name,
            "course": certificate.course,
            "issue_date": job.issue_date.isoformat(),
            "issuer_name": job.issuer_name,
        }
        generate_certificate_pdf(data, output_path)
        return CertificateResult(certificate_id, "SUCCESS", str(output_path))
    except Exception as exc:
        return CertificateResult(
            certificate_id,
            "FAILED",
            error_message=str(exc) or exc.__class__.__name__,
        )
    finally:
        if db is not None:
            db.close()


def process_job(job_id: str) -> None:
    """Process all pending rows, then derive the final job counters/status."""
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            return
        job.status = "PROCESSING"
        job.updated_at = datetime.now(timezone.utc)
        pending_ids = list(
            db.scalars(
                select(Certificate.id).where(
                    Certificate.job_id == job_id,
                    Certificate.status == "PENDING",
                )
            )
        )
        db.commit()
    finally:
        db.close()

    with ThreadPoolExecutor(max_workers=max(1, config.WORKER_THREADS)) as executor:
        results = [result for result in executor.map(_process_certificate, pending_ids) if result]

    db = SessionLocal()
    try:
        for start in range(0, len(results), 250):
            batch = results[start : start + 250]
            db.bulk_update_mappings(
                Certificate,
                [
                    {
                        "id": result.certificate_id,
                        "status": result.status,
                        "file_path": result.file_path,
                        "error_message": result.error_message,
                        "updated_at": datetime.now(timezone.utc),
                    }
                    for result in batch
                ],
            )
            db.commit()

        job = db.get(Job, job_id)
        if job is None:
            return
        count_rows = db.execute(
            select(Certificate.status, func.count())
            .where(Certificate.job_id == job_id)
            .group_by(Certificate.status)
        ).all()
        counts = {status: count for status, count in count_rows}
        successes = counts.get("SUCCESS", 0)
        failures = counts.get("FAILED", 0)
        pending = counts.get("PENDING", 0)
        job.success_count = successes
        job.failed_count = failures
        job.updated_at = datetime.now(timezone.utc)
        if pending:
            job.status = "PROCESSING"
            job.completed_at = None
        elif successes == 0:
            job.status = "FAILED"
            job.completed_at = job.updated_at
        elif failures:
            job.status = "COMPLETED_WITH_ERRORS"
            job.completed_at = job.updated_at
        else:
            job.status = "COMPLETED"
            job.completed_at = job.updated_at
        db.commit()
    finally:
        db.close()