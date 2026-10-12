"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select

from app.database import Base, SessionLocal, engine
from app.models import Job
from app.routers.jobs import router as jobs_router
from app.schemas import HealthResponse
from app.services.processor import process_job


def initialize_database_and_recover_jobs() -> None:
    """Create tables and resume pending work left by a prior server stop."""
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        job_ids = list(
            db.scalars(
                select(Job.id).where(Job.status.in_(["PENDING", "PROCESSING"]))
            )
        )
    for job_id in job_ids:
        process_job(job_id)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database_and_recover_jobs()
    yield


app = FastAPI(title="Bulk Certificate Generator API", version="1.0.0", lifespan=lifespan)
app.include_router(jobs_router, prefix="/api/v1")


@app.get("/health", response_model=HealthResponse)
def health() -> dict[str, str]:
    return {"status": "ok"}