"""Pydantic models for the public API."""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class JobCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "event_name": "Python Workshop 2026",
                    "issuer_name": "Tech Academy",
                    "issue_date": "2026-10-12",
                    "recipients": [
                        {"name": "Asha K", "email": "asha@example.com", "course": "Python Basics"}
                    ],
                }
            ]
        }
    )

    event_name: str = Field(min_length=1, max_length=200)
    issuer_name: str = Field(min_length=1, max_length=200)
    issue_date: date
    recipients: list[Any] = Field(min_length=1)

    @field_validator("event_name", "issuer_name")
    @classmethod
    def require_non_blank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class CertificateItem(BaseModel):
    id: str
    name: str
    email: str
    status: str
    error_message: str | None
    download_url: str | None = None


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    event_name: str
    issuer_name: str
    issue_date: date
    total_count: int
    success_count: int
    failed_count: int
    pending_count: int
    progress_percent: float
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    items: list[CertificateItem] | None = None


class CertificateListResponse(BaseModel):
    job_id: str
    total_count: int
    limit: int
    offset: int
    items: list[CertificateItem]


class JobCreateResponse(BaseModel):
    job_id: str
    status: str
    total_count: int
    status_url: str


class HealthResponse(BaseModel):
    status: str