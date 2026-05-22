"""Shared test fixtures.

A fixed PII_HASH_SALT is set before the app (and its engine singleton) is
imported so placeholder tokens are deterministic across the test run.
"""
from __future__ import annotations

import os

os.environ.setdefault("PII_HASH_SALT", "test-salt-deterministic")
os.environ.setdefault("PII_MASTER_KEY", "test-master-key")
os.environ.setdefault("REQUIRE_API_KEY", "false")

import pytest
from fastapi.testclient import TestClient

import app.token_store as token_store
from app.main import app


@pytest.fixture(scope="session")
def client():
    # TestClient as a context manager triggers FastAPI lifespan, which warm-starts
    # the engine (loads the spaCy models once for the whole session).
    with TestClient(app) as c:
        yield c


@pytest.fixture
def reset_store():
    """Rebuild the token store singleton so env changes (e.g. REQUIRE_API_KEY)
    take effect, and restore it afterwards."""
    original = token_store._store
    token_store._store = None
    yield
    token_store._store = original
