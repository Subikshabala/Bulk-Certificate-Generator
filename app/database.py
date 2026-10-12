"""SQLAlchemy engine and request-scoped database sessions."""

from collections.abc import Generator
import sqlite3

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import DATABASE_URL

connect_args = {"check_same_thread": False, "timeout": 30} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)


def configure_sqlite_connection(
    dbapi_connection: sqlite3.Connection, connection_record: object
) -> None:
    """Enable SQLite's write-ahead log and explicit lock wait timeout."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA journal_mode=WAL")
    finally:
        cursor.close()


if DATABASE_URL.startswith("sqlite"):
    event.listen(engine, "connect", configure_sqlite_connection)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Base class for database models."""


def get_db() -> Generator[Session, None, None]:
    """Yield one database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()