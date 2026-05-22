"""Scenario coverage for the /mask endpoint."""
from __future__ import annotations

import re

TOKEN_RE = re.compile(r"\[[A-Z_]+_[0-9a-f]{8}\]")


def _mask(client, text, **kwargs):
    body = {"text": text, "language": kwargs.pop("language", "en")}
    body.update(kwargs)
    resp = client.post("/mask", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_masks_person_email_and_returns_tokens(client):
    text = "Contact John Smith at john@acme.com please"
    data = _mask(client, text)

    # Raw PII must not survive in the masked text.
    assert "john@acme.com" not in data["masked"]
    assert "John Smith" not in data["masked"]
    assert TOKEN_RE.search(data["masked"])

    labels = {e["label"] for e in data["entities"]}
    assert "EMAIL" in labels
    assert "PERSON" in labels

    for e in data["entities"]:
        assert set(e) == {"text", "label", "token", "start", "end"}
        assert TOKEN_RE.fullmatch(e["token"])
        # Offsets point at the original value in the source text.
        assert text[e["start"]:e["end"]] == e["text"]


def test_same_value_yields_same_token_distinct_values_differ(client):
    data = _mask(client, "Email a@x.com and again a@x.com but also b@y.com")
    by_value = {}
    for e in data["entities"]:
        by_value.setdefault(e["text"], set()).add(e["token"])

    # Same value -> exactly one token.
    for value, tokens in by_value.items():
        assert len(tokens) == 1, f"{value} produced {tokens}"
    # Two different emails -> two different tokens.
    assert "a@x.com" in by_value and "b@y.com" in by_value
    assert next(iter(by_value["a@x.com"])) != next(iter(by_value["b@y.com"]))


def test_restoration_round_trip(client):
    text = "Reach John Smith at john@acme.com or call 415-555-0142"
    data = _mask(client, text)

    restored = data["masked"]
    for e in data["entities"]:
        restored = restored.replace(e["token"], e["text"])
    assert restored == text


def test_return_entities_false_omits_pii(client):
    text = "Contact John Smith at john@acme.com"
    data = _mask(client, text, return_entities=False)

    assert data["entities"] == []
    body = str(data)
    assert "John Smith" not in body
    assert "john@acme.com" not in body
    assert TOKEN_RE.search(data["masked"])


def test_spanish_detects_person(client):
    data = _mask(client, "Hola, soy Juan Pérez y vivo en Madrid", language="es")
    assert "Juan Pérez" not in data["masked"]
    assert any(e["label"] == "PERSON" for e in data["entities"])


def test_unsupported_language_returns_400(client):
    resp = client.post("/mask", json={"text": "hello", "language": "fr"})
    assert resp.status_code == 400


def test_no_pii_returns_text_unchanged(client):
    text = "the quick brown fox jumps over the lazy dog"
    data = _mask(client, text)
    assert data["masked"] == text
    assert data["entities"] == []


def test_empty_string(client):
    data = _mask(client, "")
    assert data["masked"] == ""
    assert data["entities"] == []
