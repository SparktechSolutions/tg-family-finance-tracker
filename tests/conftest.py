"""Shared pytest fixtures: an in-memory SQLite session."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
