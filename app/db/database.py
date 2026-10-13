"""Database engine/session helpers."""
from collections.abc import Generator
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from app.config import get_settings


def _make_engine():
    url = get_settings().database_url
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    engine = create_engine(url, future=True, pool_pre_ping=True, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def init_db() -> None:
    from app.db.models import Base
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
