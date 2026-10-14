"""Shared fixtures for tests that need the database and the HTTP API.

Uses SQLite in memory so the suite runs without Postgres. Postgres-specific
behaviour (the partial unique index) is covered by running migrations in CI.
"""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.api import app, get_enqueue  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.db.session import get_session  # noqa: E402


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def enqueued():
    return []


@pytest.fixture
def client(session_factory, enqueued):
    def _session():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_enqueue] = lambda: enqueued.append
    yield TestClient(app)
    app.dependency_overrides.clear()
