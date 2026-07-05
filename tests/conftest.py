"""Shared fixtures: a fresh database per test.

By default each test gets its own temp SQLite file. Set CONFLUX_TEST_DATABASE_URL
(e.g. a PostgreSQL URL) to run the same suite against that backend instead, with
the schema dropped and recreated per test for isolation.
"""

import os
import tempfile

import pytest

from conflux import db, service
from conflux.db import Base


@pytest.fixture
def fresh_db():
    url = os.environ.get("CONFLUX_TEST_DATABASE_URL")
    if url:
        db.init_db(url)
        Base.metadata.drop_all(db._engine)
        Base.metadata.create_all(db._engine)
        try:
            yield
        finally:
            Base.metadata.drop_all(db._engine)
            db._engine = None
            db._SessionLocal = None
        return

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db.init_db(f"sqlite:///{path}")
    try:
        yield
    finally:
        db._engine = None
        db._SessionLocal = None
        os.unlink(path)


@pytest.fixture
def subject(fresh_db):
    """One subject; returns its id."""
    return service.create_subject("Test Subject", "KE0TST")
