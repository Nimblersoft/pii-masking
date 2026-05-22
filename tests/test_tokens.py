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
