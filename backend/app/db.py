"""Database engine and session management (SQLite for local demo, PostgreSQL for compose/prod)."""
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """Naive UTC timestamp. Stored naive everywhere so SQLite and PostgreSQL behave the same."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def init_engine(url: str | None = None) -> Engine:
    global _engine, _SessionLocal
    url = url or get_settings().database_url
    kwargs: dict = {"pool_pre_ping": True}
    is_sqlite = url.startswith("sqlite")
    if is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        path = url.replace("sqlite:///", "", 1)
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
    if _engine is not None:
        _engine.dispose()
    _engine = create_engine(url, **kwargs)
    if is_sqlite:
        @event.listens_for(_engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_engine() -> Engine:
    return _engine if _engine is not None else init_engine()


def new_session() -> Session:
    if _SessionLocal is None:
        init_engine()
    return _SessionLocal()  # type: ignore[misc]


def get_db():
    db = new_session()
    try:
        yield db
    finally:
        db.close()


def create_schema() -> None:
    # Milestone 1 uses create_all. Production work: Alembic migrations (see docs/STATUS.md).
    from app import models  # noqa: F401 - register models

    Base.metadata.create_all(get_engine())


def drop_schema() -> None:
    from app import models  # noqa: F401

    Base.metadata.drop_all(get_engine())
