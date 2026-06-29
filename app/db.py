"""Database engine + session helpers (SQLAlchemy 2.0)."""
import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from .config import settings

log = logging.getLogger("db")

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


def _auto_migrate(Base) -> None:
    """Poor-man's migration: add any model columns missing from existing tables.

    `create_all` makes new tables but never alters existing ones, so when we add a column
    (e.g. expenses.shared) an older database would be missing it. This adds those columns
    via ALTER TABLE … ADD COLUMN with their default, so upgrades never lose data. For a
    production deployment, replace this with Alembic.
    """
    insp = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing:
                continue
            coltype = col.type.compile(engine.dialect)
            default_sql = ""
            d = getattr(col.default, "arg", None) if col.default is not None else None
            if d is not None and not callable(d):
                if isinstance(d, bool):
                    default_sql = f" DEFAULT {1 if d else 0}"
                elif isinstance(d, (int, float)):
                    default_sql = f" DEFAULT {d}"
                else:
                    default_sql = f" DEFAULT '{d}'"
            try:
                with engine.begin() as conn:
                    conn.execute(text(
                        f'ALTER TABLE {table.name} ADD COLUMN {col.name} {coltype}{default_sql}'))
                log.info("migrated: added %s.%s", table.name, col.name)
            except Exception:  # noqa: BLE001 - best-effort; never block startup
                log.exception("could not add column %s.%s", table.name, col.name)


def init_db() -> None:
    """Create any missing tables, then add any missing columns to existing tables."""
    from .models import Base  # local import to avoid circulars

    Base.metadata.create_all(bind=engine)
    _auto_migrate(Base)
