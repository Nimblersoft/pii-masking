"""E2E: boot the real uvicorn server as a subprocess and drive it over HTTP.

Unlike the TestClient suites (in-process), this exercises the deployment
path: real sockets, uvicorn, lifespan warm-start, header auth, and the
token lifecycle — everything a client of the service would experience.
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.e2e

# tests/e2e/test_e2e_service.py -> tests/e2e/ -> tests/ -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]

MASTER_KEY = "e2e-master-key"
HASH_SALT = "e2e-salt-stable"
# pii_ + 40 hex chars, matching the documented API-token format.
SEEDED_TOKEN = "pii_" + "e2e5eeded" + "0" * 31

TOKEN_RE = re.compile(r"\[[A-Z_]+_[0-9a-f]{8}\]")

STARTUP_TIMEOUT_S = 90


@pytest.fixture(scope="session")
def server():
    # Bind a listening socket and hand it to uvicorn via --fd: the kernel
    # guarantees the port, so no other process can claim it in between
    # (no TOCTOU window) and the health check can never hit a stranger.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    fd = str(sock.fileno())

    # Minimal passthrough + overrides. INFISICAL_* is scrubbed so the E2E
    # server can never reach for host/CI Infisical credentials, even if a
    # future change starts honoring them outside entrypoint.sh.
    env = {k: v for k, v in os.environ.items() if not k.startswith("INFISICAL_")}
    env.update(
        PII_MASTER_KEY=MASTER_KEY,
        PII_HASH_SALT=HASH_SALT,
        REQUIRE_API_KEY="true",
        PII_API_TOKEN=SEEDED_TOKEN,
    )

    log = tempfile.NamedTemporaryFile(
        mode="w+", prefix="pii-e2e-uvicorn-", suffix=".log", delete=False
    )
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "app.main:app",
            "--fd", fd, "--log-level", "warning",
        ],
        cwd=REPO_ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        pass_fds=(sock.fileno(),),
    )
    sock.close()  # the child owns its own duplicate now
    base_url = f"http://127.0.0.1:{port}"

    def _log_tail() -> str:
        log.flush()
        with open(log.name) as f:
            return "".join(f.readlines()[-40:])

    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    try:
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                pytest.fail(f"uvicorn died during startup:\n{_log_tail()}")
            try:
                if httpx.get(f"{base_url}/health", timeout=2).status_code == 200:
                    break
            except httpx.TransportError:
                pass
            time.sleep(0.3)
        else:
            pytest.fail(f"server did not become healthy in {STARTUP_TIMEOUT_S}s:\n{_log_tail()}")
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        log.close()
        try:
            os.unlink(log.name)
        except OSError:
            pass


@pytest.fixture()
def client(server):
    with httpx.Client(base_url=server, timeout=30) as c:
        yield c


def test_health_reports_status_and_models(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert sorted(body["models"]) == ["en", "es"]


def test_mask_rejects_missing_api_key(client):
    resp = client.post("/mask", json={"text": "John Smith", "language": "en"})
    assert resp.status_code == 401


def test_mask_rejects_wrong_api_key(client):
    resp = client.post(
        "/mask",
        json={"text": "John Smith", "language": "en"},
        headers={"X-API-Key": "pii_bogus"},
    )
    assert resp.status_code == 401


def test_seeded_token_from_env_authenticates(client):
    """PII_API_TOKEN seeded at boot must gate /mask immediately — the
    container self-provisioning path (see app/main.py lifespan)."""
    resp = client.post(
        "/mask",
        json={"text": "no pii here", "language": "en"},
        headers={"X-API-Key": SEEDED_TOKEN},
    )
    assert resp.status_code == 200
    assert resp.json()["masked"] == "no pii here"


def test_mask_journey_en(client):
    text = "Reach John Smith at john@acme.com or call 415-555-0142"
    resp = client.post(
        "/mask",
        json={"text": text, "language": "en"},
        headers={"X-API-Key": SEEDED_TOKEN},
    )
    assert resp.status_code == 200
    body = resp.json()

    # Raw PII must not survive in the masked text.
    for raw in ("John Smith", "john@acme.com", "415-555-0142"):
        assert raw not in body["masked"]
    assert TOKEN_RE.search(body["masked"])

    labels = {e["label"] for e in body["entities"]}
    assert "PERSON" in labels and "EMAIL" in labels and "PHONE" in labels
    for e in body["entities"]:
        assert TOKEN_RE.fullmatch(e["token"])
        # Offsets point at the original value in the source text.
        assert text[e["start"]:e["end"]] == e["text"]

    # Restoration round-trip: the caller re-derives the original text.
    restored = body["masked"]
    for e in body["entities"]:
        restored = restored.replace(e["token"], e["text"])
    assert restored == text


def test_token_stable_across_requests(client):
    """Cross-request consistency given a stable salt (ADR 0001)."""
    headers = {"X-API-Key": SEEDED_TOKEN}
    first = client.post(
        "/mask", json={"text": "mail a@x.com", "language": "en"}, headers=headers
    ).json()
    second = client.post(
        "/mask", json={"text": "mail a@x.com", "language": "en"}, headers=headers
    ).json()
    tok1 = {e["text"]: e["token"] for e in first["entities"]}
    tok2 = {e["text"]: e["token"] for e in second["entities"]}
    assert tok1, "no entities detected — stability unverified"
    assert tok1 == tok2


def test_mask_spanish(client):
    resp = client.post(
        "/mask",
        json={"text": "Hola, soy Juan Pérez y vivo en Madrid", "language": "es"},
        headers={"X-API-Key": SEEDED_TOKEN},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "Juan Pérez" not in body["masked"]
    assert any(e["label"] == "PERSON" for e in body["entities"])


def test_return_entities_false_omits_pii(client):
    resp = client.post(
        "/mask",
        json={"text": "Contact John Smith at john@acme.com", "return_entities": False},
        headers={"X-API-Key": SEEDED_TOKEN},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["entities"] == []
    assert "John Smith" not in resp.text and "john@acme.com" not in resp.text
    assert TOKEN_RE.search(body["masked"])


def test_unsupported_language_returns_400(client):
    resp = client.post(
        "/mask",
        json={"text": "bonjour", "language": "fr"},
        headers={"X-API-Key": SEEDED_TOKEN},
    )
    assert resp.status_code == 400
    assert "detail" in resp.json()


def test_bearer_auth_accepted(client):
    resp = client.post(
        "/mask",
        json={"text": "hello world", "language": "en"},
        headers={"Authorization": f"Bearer {SEEDED_TOKEN}"},
    )
    assert resp.status_code == 200


def test_admin_rejects_wrong_master_key(client):
    resp = client.get("/tokens", headers={"X-Master-Key": "wrong"})
    assert resp.status_code == 401


def test_token_admin_lifecycle(client):
    admin = {"X-Master-Key": MASTER_KEY}

    # Create — raw token returned exactly once.
    created = client.post("/tokens", headers=admin)
    assert created.status_code == 200
    raw = created.json()["token"]
    token_id = created.json()["id"]
    assert raw.startswith("pii_") and len(raw) == 4 + 40

    # New token authorizes /mask (X-API-Key and Bearer).
    for headers in ({"X-API-Key": raw}, {"Authorization": f"Bearer {raw}"}):
        resp = client.post(
            "/mask", json={"text": "hello world", "language": "en"}, headers=headers
        )
        assert resp.status_code == 200

    # List — metadata only; raw value and hash are never echoed.
    listed = client.get("/tokens", headers=admin).json()["tokens"]
    entry = next(t for t in listed if t["id"] == token_id)
    assert "hash" not in entry and "token" not in entry
    assert {"id", "prefix", "created_at", "last_used"}.issubset(entry)
    assert entry["last_used"] is not None

    # Revoke — then the token stops authorizing /mask; re-revoke 404s.
    assert client.delete(f"/tokens/{token_id}", headers=admin).status_code == 200
    resp = client.post(
        "/mask", json={"text": "hello", "language": "en"}, headers={"X-API-Key": raw}
    )
    assert resp.status_code == 401
    assert client.delete(f"/tokens/{token_id}", headers=admin).status_code == 404
