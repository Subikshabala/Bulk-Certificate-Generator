"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from threading import Thread

from fastapi import FastAPI
from sqlalchemy import select

from app.database import Base, SessionLocal, engine
from app.models import Certificate, Job
from app.routers.jobs import router as jobs_router
from app.schemas import HealthResponse
from app.services.processor import process_job


def initialize_database() -> None:
    """Create database tables before serving requests."""
    Base.metadata.create_all(bind=engine)


def recover_unfinished_jobs() -> None:
    """Resume pending certificates for unfinished jobs from a previous run."""
    with SessionLocal() as db:
        job_ids = list(
            db.scalars(
                select(Job.id)
                .where(
                    Job.status.in_(["PENDING", "PROCESSING"]),
                    Job.id.in_(
                        select(Certificate.job_id)
                        .where(Certificate.status == "PENDING")
                        .distinct()
                    ),
                )
            )
        )
    for job_id in job_ids:
        process_job(job_id)


def initialize_database_and_recover_jobs() -> None:
    """Run database initialization and recovery synchronously for tests/tools."""
    initialize_database()
    recover_unfinished_jobs()


def start_recovery_thread() -> Thread:
    """Start crash recovery without blocking request acceptance."""
    thread = Thread(
        target=recover_unfinished_jobs,
        name="certificate-recovery",
        daemon=True,
    )
    thread.start()
    return thread


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database()
    start_recovery_thread()
    yield


app = FastAPI(title="Bulk Certificate Generator API", version="1.0.0", lifespan=lifespan)
app.include_router(jobs_router, prefix="/api/v1")


@app.get("/health", response_model=HealthResponse)
def health() -> dict[str, str]:
    return {"status": "ok"}