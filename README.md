# Bulk Certificate Generator

A small FastAPI service that accepts a batch of recipients, records per-recipient validation results, and generates downloadable PDF completion certificates.

## Setup

Requires Python 3.11 or newer.

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

### macOS and Linux

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` to choose a database URL, storage directory, maximum batch size, or worker count. SQLite is the default. For PostgreSQL, use a URL such as `postgresql+psycopg://user:password@localhost/database`; the psycopg driver is included in the requirements.

## Run

```powershell
python -m uvicorn app.main:app --reload
```

The service is available at `http://127.0.0.1:8000`; interactive API documentation is at `/docs`. On Windows, plain `uvicorn` may not be on `PATH`; `python -m uvicorn` uses the active environment explicitly.

## Tests

```powershell
pytest
```

The tests use a temporary SQLite database and certificate directory.

## Example Requests

Submit a job:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/jobs \\
  -H "Content-Type: application/json" \\
  --data-binary "@sample_request.json"
```

PowerShell:

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/jobs -H "Content-Type: application/json" --data-binary "@sample_request.json"
```

The sample contains eight valid and invalid recipient entries, including a Tamil name and a case-different duplicate email.

Check job status and recipient outcomes:

```bash
curl "http://127.0.0.1:8000/api/v1/jobs/JOB_ID?include_items=true&limit=100&offset=0"
```

List successful certificates:

```bash
curl "http://127.0.0.1:8000/api/v1/jobs/JOB_ID/certificates?status=SUCCESS&limit=100&offset=0"
```

Download one PDF or the ZIP of successful certificates:

```bash
curl -o certificate.pdf "http://127.0.0.1:8000/api/v1/certificates/CERTIFICATE_ID/download"
curl -o certificates.zip "http://127.0.0.1:8000/api/v1/jobs/JOB_ID/download"
```

## API Reference

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness check |
| `POST` | `/api/v1/jobs` | Validate recipients, create a job, and queue generation; returns 202 |
| `GET` | `/api/v1/jobs/{job_id}` | Job state, counts, progress, and optional paginated items |
| `GET` | `/api/v1/jobs/{job_id}/certificates` | Paginated recipient results; optional `status` filter |
| `GET` | `/api/v1/certificates/{certificate_id}/download` | Download one generated PDF |
| `GET` | `/api/v1/jobs/{job_id}/download` | Download a ZIP of generated PDFs |

Request-level validation failures return 422 without creating a job. Unknown IDs return 404. Downloads that are pending, failed, or unavailable return 409. Each certificate-list item includes a PDF download URL only after successful generation.

## Design Decisions

- **FastAPI:** concise typed request handling, generated OpenAPI docs, and built-in background tasks.
- **Database:** SQLAlchemy 2 synchronous sessions keep persistence clear and work with SQLite by default or PostgreSQL with a driver.
- **Background processing:** synchronous rendering would hold the request open for the whole batch. FastAPI `BackgroundTasks` returns the 202 response first, and a bounded `ThreadPoolExecutor` limits concurrent PDF rendering without adding Celery/Redis infrastructure. This is intentionally an in-process solution, not a durable queue; Celery/Redis is the next step when workloads need persistent retries or multiple workers.
- **Failure isolation:** each worker owns a database session and processes one certificate inside its own exception boundary, so one bad render does not stop the batch.
- **Validation:** required job fields, malformed JSON, and recipient-list size are request-level checks. Name, email normalization, and case-insensitive duplicate checks run per recipient; invalid rows remain visible with an explanation, while the first occurrence of a valid address is retained.
- **File storage:** PDF files are placed under `CERT_STORAGE_DIR/<job_id>/<certificate_id>.pdf`; path containment is checked and directory/file names use generated IDs rather than user text. ZIP downloads use a spooled temporary file and stream it in chunks.
- **Recovery:** startup creates tables synchronously, then starts crash recovery in a daemon thread so the server can accept requests immediately. Recovery considers only unfinished jobs with `PENDING` certificate rows; `initialize_database_and_recover_jobs()` remains available for deterministic synchronous tests.
- **PDF fonts:** bundled Noto Sans and Noto Sans Tamil support Latin, Greek, Cyrillic, and Tamil. ReportLab uses HarfBuzz shaping through the pinned `uharfbuzz` dependency for complex Tamil text. Devanagari and CJK are not supported by these bundled fonts.

## Limitations and Next Improvements

In-process background work can be lost if the process stops during a render. Startup recovery retries rows still pending, but it is not a durable queue. At higher scale, move processing to Celery/Redis. Other useful next steps are S3-compatible storage, authentication and authorization, rate limiting, idempotency keys, and database migrations. The fixed PDF template is a single page. Add other Noto language fonts if Devanagari, CJK, or additional writing systems are required.