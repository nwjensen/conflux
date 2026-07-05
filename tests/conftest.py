"""Shared fixtures: a fresh temp database per test."""

import os
import tempfile

import pytest

from conflux import db, service


@pytest.fixture
def fresh_db():
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
