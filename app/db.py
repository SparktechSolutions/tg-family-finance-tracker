"""Database engine + session helpers (SQLAlchemy 2.0)."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_session():
    """FastAPI dependency that yields a DB session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """Create tables. For real migrations later, swap to Alembic."""
    from .models import Base  # local import to avoid circulars

    Base.metadata.create_all(bind=engine)
