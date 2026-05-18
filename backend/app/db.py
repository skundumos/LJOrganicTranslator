from collections.abc import Iterator
from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings

_engine = create_engine(
    settings.DB_URL,
    echo=False,
    connect_args={"check_same_thread": False} if settings.DB_URL.startswith("sqlite") else {},
)


def init_db() -> None:
    from app import models  # noqa: F401  (register tables)

    SQLModel.metadata.create_all(_engine)
    _apply_lightweight_migrations()


def _apply_lightweight_migrations() -> None:
    """Idempotent ADD COLUMN for fields added after the table already exists.

    SQLite supports ALTER TABLE ADD COLUMN but we have to check first because
    re-adding an existing column raises. Sufficient for this project — no full
    Alembic setup needed.
    """
    insp = inspect(_engine)
    if "videojob" not in insp.get_table_names():
        return  # fresh DB, create_all already added everything
    existing = {col["name"] for col in insp.get_columns("videojob")}
    if "regions" not in existing:
        with _engine.begin() as conn:
            conn.execute(text("ALTER TABLE videojob ADD COLUMN regions JSON"))


def get_session() -> Iterator[Session]:
    with Session(_engine) as session:
        yield session


def session_scope() -> Session:
    return Session(_engine)
