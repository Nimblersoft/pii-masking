"""Auth surface coverage for the /tokens admin endpoints and X-API-Key gating."""
from __future__ import annotations

import os

MASTER_KEY = os.environ["PII_MASTER_KEY"]


def test_tokens_rejects_missing_master_key(client):
    assert client.get("/tokens").status_code == 401
    assert client.post("/tokens").status_code == 401


def test_tokens_rejects_invalid_master_key(client):
    headers = {"X-Master-Key": "wrong"}
    assert client.get("/tokens", headers=headers).status_code == 401


def test_create_token_returns_raw_value_once(client):
    headers = {"X-Master-Key": MASTER_KEY}
    resp = client.post("/tokens", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token"].startswith("pii_")
    assert body["id"]

    # Listing never echoes the raw token back.
    listed = client.get("/tokens", headers=headers).json()
    assert all("token" not in t for t in listed["tokens"])
    assert any(t["id"] == body["id"] for t in listed["tokens"])


def test_mask_requires_api_key_when_enforced(client, reset_store, monkeypatch):
    monkeypatch.setenv("REQUIRE_API_KEY", "true")
    # reset_store cleared the singleton; next request rebuilds it reading the env.
    resp = client.post("/mask", json={"text": "John Smith", "language": "en"})
    assert resp.status_code == 401


def test_mask_accepts_bearer_auth(client, reset_store, monkeypatch):
    """Authorization: Bearer <token> should be accepted when REQUIRE_API_KEY=true."""
    monkeypatch.setenv("REQUIRE_API_KEY", "true")
    from app.token_store import get_store as _gs

    store = _gs()
    created = store.create_token()
    raw = created["token"]

    resp = client.post(
        "/mask",
        json={"text": "John Smith", "language": "en"},
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert resp.status_code == 200, resp.text


def test_mask_accepts_x_api_key(client, reset_store, monkeypatch):
    """X-API-Key header should still be accepted (backward compat)."""
    monkeypatch.setenv("REQUIRE_API_KEY", "true")
    from app.token_store import get_store as _gs

    store = _gs()
    created = store.create_token()
    raw = created["token"]

    resp = client.post(
        "/mask",
        json={"text": "John Smith", "language": "en"},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200, resp.text


def test_mask_rejects_bad_bearer(client, reset_store, monkeypatch):
    """A wrong Bearer token must still be rejected."""
    monkeypatch.setenv("REQUIRE_API_KEY", "true")
    from app.token_store import get_store as _gs
    _gs()  # force store init

    resp = client.post(
        "/mask",
        json={"text": "John Smith", "language": "en"},
        headers={"Authorization": "Bearer pii_bogus"},
    )
    assert resp.status_code == 401


def test_seed_token_and_verify(reset_store, monkeypatch):
    """seed_token() should register a raw token that passes verify_token()."""
    monkeypatch.setenv("REQUIRE_API_KEY", "true")
    from app.token_store import get_store as _gs

    store = _gs()
    raw = "pii_abcdef1234567890abcdef1234567890abcdef12"
    store.seed_token(raw)
    assert store.verify_token(raw)


def test_seed_token_idempotent(reset_store, monkeypatch):
    """Seeding the same token twice should not duplicate it."""
    monkeypatch.setenv("REQUIRE_API_KEY", "true")
    from app.token_store import get_store as _gs

    store = _gs()
    raw = "pii_deadbeef0000111122223333444455556666aabb"
    store.seed_token(raw)
    store.seed_token(raw)  # second call — should be no-op
    tokens = store.list_tokens()
    # Only one entry should exist for this token prefix
    matching = [t for t in tokens if raw.startswith(t["prefix"])]
    assert len(matching) == 1

