"""Database engine + session helpers (PostgreSQL in production, SQLite locally)."""
from __future__ import annotations

import contextlib
from typing import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from etl.config import DB_KIND, database_url

_engine: Engine | None = None


def get_engine(echo: bool = False) -> Engine:
    """Singleton SQLAlchemy engine with sane pooling for both backends."""
    global _engine
    if _engine is None:
        url = database_url()
        kwargs: dict = {"future": True, "echo": echo, "pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
            _engine = create_engine(url, **kwargs)

            @event.listens_for(_engine, "connect")
            def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA foreign_keys=ON")
                cur.execute("PRAGMA synchronous=NORMAL")
                cur.close()
        else:
            kwargs["pool_size"] = 10
            kwargs["max_overflow"] = 20
            _engine = create_engine(url, **kwargs)
    return _engine


def get_session_factory() -> sessionmaker:
    return sessionmaker(bind=get_engine(), future=True, expire_on_commit=False)


@contextlib.contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, rollback on any exception."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def healthcheck() -> dict:
    """Lightweight connectivity probe used by /health."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"database": "up", "backend": DB_KIND, "url_scheme": database_url().split("://")[0]}
    except Exception as exc:  # pragma: no cover - surfaced to the API
        return {"database": "down", "backend": DB_KIND, "error": str(exc)}
