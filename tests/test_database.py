from sqlalchemy import create_engine, event

from app.database import configure_sqlite_connection


def test_sqlite_connections_use_wal_and_busy_timeout(tmp_path):
    database_path = (tmp_path / "wal.db").as_posix()
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    event.listen(engine, "connect", configure_sqlite_connection)
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
            assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 30000
    finally:
        engine.dispose()