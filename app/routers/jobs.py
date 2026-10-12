"""Job, certificate listing, and download endpoints."""

import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Iterator

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config
from app.database import get_db
from app.models import Certificate, Job
from app.schemas import (
    CertificateItem,
    CertificateListResponse,
    JobCreate,
    JobCreateResponse,
    JobStatusResponse,
)
from app.services.processor import process_job

router = APIRouter()


def _recipient_values(
    raw: object,
) -> tuple[str, str, str | None, list[str], str | None]:
    """Return cleaned values, validation errors, and a valid normalized email."""
    if not isinstance(raw, dict):
        return "", "", None, ["Recipient must be a JSON object."], None
    name_value = raw.get("name")
    email_value = raw.get("email")
    name = name_value.strip() if isinstance(name_value, str) else ""
    email = email_value.strip() if isinstance(email_value, str) else ""
    course_value = raw.get("course")
    course = course_value.strip()[:200] if isinstance(course_value, str) and course_value.strip() else None
    errors = []
    if not name:
        errors.append("Name is required and must not be blank.")
    elif len(name) > 100:
        errors.append("Name must be at most 100 characters.")
        name = name[:100]
    normalized_email = None
    try:
        normalized_email = validate_email(email, check_deliverability=False).normalized.casefold()
    except EmailNotValidError:
        errors.append("Email address is invalid.")
    return name, normalized_email or email, course, errors, normalized_email


def _certificate_item(certificate: Certificate) -> CertificateItem:
    download_url = (
        f"/api/v1/certificates/{certificate.id}/download"
        if certificate.status == "SUCCESS"
        else None
    )
    return CertificateItem(
        id=certificate.id,
        name=certificate.recipient_name,
        email=certificate.recipient_email,
        status=certificate.status,
        error_message=certificate.error_message,
        download_url=download_url,
    )


@router.post("/jobs", status_code=status.HTTP_202_ACCEPTED, response_model=JobCreateResponse)
def create_job(
    request: JobCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> JobCreateResponse:
    """Persist recipient results and queue generation for valid rows."""
    if len(request.recipients) > config.MAX_RECIPIENTS_PER_JOB:
        raise HTTPException(
            status_code=422,
            detail=f"A job may contain at most {config.MAX_RECIPIENTS_PER_JOB} recipients.",
        )

    job = Job(
        event_name=request.event_name,
        issuer_name=request.issuer_name,
        issue_date=request.issue_date,
        total_count=len(request.recipients),
    )
    db.add(job)
    db.flush()
    seen_emails: set[str] = set()
    invalid_count = 0
    for raw in request.recipients:
        name, email, course, errors, normalized_email = _recipient_values(raw)
        if normalized_email:
            if normalized_email in seen_emails:
                errors.append("Duplicate email address in this job.")
            else:
                seen_emails.add(normalized_email)
        error = " ".join(errors) or None
        certificate = Certificate(
            job_id=job.id,
            recipient_name=name,
            recipient_email=email,
            status="FAILED" if errors else "PENDING",
            error_message=error,
            course=course,
        )
        if errors:
            invalid_count += 1
        db.add(certificate)

    job.failed_count = invalid_count
    if invalid_count == job.total_count:
        job.status = "FAILED"
        job.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    if job.status != "FAILED":
        background_tasks.add_task(process_job, job.id)

    return JobCreateResponse(
        job_id=job.id,
        status=job.status,
        total_count=job.total_count,
        status_url=f"/api/v1/jobs/{job.id}",
    )


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job(
    job_id: str,
    include_items: bool = False,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> JobStatusResponse:
    """Return current job counts and optionally a page of recipients."""
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    success_count = db.scalar(
        select(func.count()).select_from(Certificate).where(
            Certificate.job_id == job_id, Certificate.status == "SUCCESS"
        )
    ) or 0
    failed_count = db.scalar(
        select(func.count()).select_from(Certificate).where(
            Certificate.job_id == job_id, Certificate.status == "FAILED"
        )
    ) or 0
    pending_count = db.scalar(
        select(func.count()).select_from(Certificate).where(
            Certificate.job_id == job_id, Certificate.status == "PENDING"
        )
    ) or 0
    items = None
    if include_items:
        rows = db.scalars(
            select(Certificate)
            .where(Certificate.job_id == job_id)
            .order_by(Certificate.created_at, Certificate.id)
            .limit(limit)
            .offset(offset)
        ).all()
        items = [_certificate_item(item) for item in rows]
    progress = (success_count + failed_count) / job.total_count * 100 if job.total_count else 0
    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        event_name=job.event_name,
        issuer_name=job.issuer_name,
        issue_date=job.issue_date,
        total_count=job.total_count,
        success_count=success_count,
        failed_count=failed_count,
        pending_count=pending_count,
        progress_percent=round(progress, 2),
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
        items=items,
    )


@router.get("/jobs/{job_id}/certificates", response_model=CertificateListResponse)
def list_certificates(
    job_id: str,
    status_filter: str | None = Query(default=None, alias="status", pattern="^(SUCCESS|FAILED|PENDING)$"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> CertificateListResponse:
    """List a page of certificate results, optionally filtered by status."""
    if db.get(Job, job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    query = select(Certificate).where(Certificate.job_id == job_id)
    count_query = select(func.count()).select_from(Certificate).where(Certificate.job_id == job_id)
    if status_filter:
        query = query.where(Certificate.status == status_filter)
        count_query = count_query.where(Certificate.status == status_filter)
    rows = db.scalars(query.order_by(Certificate.created_at, Certificate.id).limit(limit).offset(offset)).all()
    return CertificateListResponse(
        job_id=job_id,
        total_count=db.scalar(count_query) or 0,
        limit=limit,
        offset=offset,
        items=[_certificate_item(item) for item in rows],
    )


@router.get("/certificates/{certificate_id}/download", response_class=FileResponse, response_model=None)
def download_certificate(certificate_id: str, db: Session = Depends(get_db)) -> FileResponse:
    """Download a successfully generated PDF."""
    certificate = db.get(Certificate, certificate_id)
    if certificate is None:
        raise HTTPException(status_code=404, detail="Certificate not found.")
    if certificate.status != "SUCCESS" or not certificate.file_path:
        raise HTTPException(status_code=409, detail="Certificate is not ready for download.")
    path = Path(certificate.file_path)
    resolved_path = path.resolve()
    if not resolved_path.is_relative_to(config.CERT_STORAGE_DIR.resolve()) or not resolved_path.is_file():
        raise HTTPException(status_code=409, detail="Certificate file is not available.")
    return FileResponse(resolved_path, media_type="application/pdf", filename=f"{certificate.id}.pdf")


def _stream_file(file_obj: BinaryIO) -> Iterator[bytes]:
    """Yield a temporary ZIP file in bounded chunks and always close it."""
    try:
        while chunk := file_obj.read(64 * 1024):
            yield chunk
    finally:
        file_obj.close()


@router.get("/jobs/{job_id}/download", response_class=StreamingResponse, response_model=None)
def download_job_zip(job_id: str, db: Session = Depends(get_db)) -> StreamingResponse:
    """Download a ZIP containing every successful certificate PDF."""
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    rows = db.scalars(
        select(Certificate).where(
            Certificate.job_id == job_id,
            Certificate.status == "SUCCESS",
            Certificate.file_path.is_not(None),
        )
    ).all()
    storage_root = config.CERT_STORAGE_DIR.resolve()
    ready = []
    for item in rows:
        path = Path(item.file_path or "").resolve()
        if path.is_relative_to(storage_root) and path.is_file():
            ready.append((item, path))
    if not ready:
        raise HTTPException(status_code=409, detail="No certificates are ready for download.")
    archive_file = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
    with zipfile.ZipFile(archive_file, "w", zipfile.ZIP_DEFLATED) as archive:
        for item, path in ready:
            archive.write(path, arcname=f"{item.id}.pdf")
    archive_file.seek(0)
    return StreamingResponse(
        _stream_file(archive_file),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{job.id}.zip"'},
    )