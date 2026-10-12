"""Environment-backed application settings."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./certificates.db")
CERT_STORAGE_DIR = Path(os.getenv("CERT_STORAGE_DIR", "./certificate_files"))
MAX_RECIPIENTS_PER_JOB = int(os.getenv("MAX_RECIPIENTS_PER_JOB", "5000"))
WORKER_THREADS = int(os.getenv("WORKER_THREADS", "4"))