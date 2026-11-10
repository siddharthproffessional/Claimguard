from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings

Base = declarative_base()
engine = None
SessionLocal = None


def configure(url: str | None = None):
    """(Re)bind the engine. Tests call this with an in-memory URL."""
    global engine, SessionLocal
    url = url or settings.database_url
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    if ":memory:" in url:
        kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return engine


def init_db():
    from app.models import models  # noqa: F401  (register tables)
    Base.metadata.create_all(engine)


def reset_db():
    from app.models import models  # noqa: F401
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


configure()
