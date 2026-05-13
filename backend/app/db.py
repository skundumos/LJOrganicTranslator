from collections.abc import Iterator
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


def get_session() -> Iterator[Session]:
    with Session(_engine) as session:
        yield session


def session_scope() -> Session:
    return Session(_engine)
