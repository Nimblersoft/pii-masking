"""Unit and API tests for Ecuadorian financial/identity recognizers,
entities filtering, allow_list overlap exclusion, and Spanish false-positive suppression.
"""
from __future__ import annotations

import re

import pytest
from presidio_anonymizer.entities import RecognizerResult

from app.pii_engine import (
    ALLOW_LIST_MAX_ITEM_LEN,
    ALLOW_LIST_MAX_ITEMS,
    _filter_allow_list,
    _find_allow_list_spans,
    resolve_entities,
)
from app.recognizers import is_valid_ec_cedula, is_valid_ec_ruc

TOKEN_RE = re.compile(r"\[[A-Z_]+_[0-9a-f]{8}\]")

# Dual-valid number: valid Guayas (09) cedula (3rd digit 5, mod-10 valid)
# AND valid Ecuadorian mobile phone in phonenumbers metadata.
DUAL_VALID_CEDULA_PHONE = "0958901233"

SYNTHETIC_BANKING_SENTENCE = (
    "Hola soy Juan Pérez, mi cédula es 1710034065, RUC 1710034065001, "
    "tel 0991234567, cuenta 2204589123, mi clave es Secreta99, "
    "quiero abrir Cuenta Ahorro Ordinario en Cooperativa San Cristóbal."
)


def _mask(client, text, **kwargs):
    body = {"text": text, "language": kwargs.pop("language", "es")}
    body.update(kwargs)
    resp = client.post("/mask", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Unit tests: Ecuadorian cédula & RUC validators
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "1710034065",   # Pichincha (17)
        "171003406-5",  # Hyphenated
        "0102030400",   # Azuay (01), check digit 0
        "0958901233",   # Guayas (09), 3rd digit 5
        "2410034066",   # Santa Elena (24)
        "3010034068",   # Foreign resident (30)
    ],
)
def test_is_valid_ec_cedula_accepts_valid(value):
    assert is_valid_ec_cedula(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "1710034064",     # Wrong check digit
        "0010034065",     # Province 00 invalid
        "2510034065",     # Province 25 invalid
        "9910034065",     # Province 99 invalid
        "1760034065",     # 3rd digit 6 invalid for cedula
        "1790034065",     # 3rd digit 9 invalid for cedula
        "0991234567",     # Phone number (3rd digit 9)
        "171003406",      # Too short (9 digits)
        "17100340650",    # Too long (11 digits)
        "1710034065001",  # 13-digit RUC, not cedula
        "17100-34065",    # Misplaced hyphen
        "171003406A",     # Non-digit
    ],
)
def test_is_valid_ec_cedula_rejects_invalid(value):
    assert is_valid_ec_cedula(value) is False


@pytest.mark.parametrize(
    "value",
    [
        "1710034065001",   # Natural person (001)
        "1710034065002",   # Natural person branch (002)
        "1710034065-001",  # Hyphenated natural person
        "3010034068001",   # Province 30 natural person
        "1790010937001",   # Private entity (3rd digit 9, mod-11)
        "1760013210001",   # Public entity (3rd digit 6, mod-11)
        "1760004650001",   # Public entity (3rd digit 6, mod-11)
    ],
)
def test_is_valid_ec_ruc_accepts_valid(value):
    assert is_valid_ec_ruc(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "1710034065000",   # Establishment 000 invalid
        "1710034064001",   # Natural person bad check digit
        "0010034065001",   # Invalid province 00
        "2510034065001",   # Invalid province 25
        "1770034065001",   # Invalid 3rd digit 7
        "1780034065001",   # Invalid 3rd digit 8
        "1790010938001",   # Private entity bad check digit
        "1760013220001",   # Public entity bad check digit
        "1760013211001",   # Public entity 10th digit != 0
        "1710034065",      # 10 digits (too short)
        "17100340650012",  # 14 digits (too long)
    ],
)
def test_is_valid_ec_ruc_rejects_invalid(value):
    assert is_valid_ec_ruc(value) is False


# ---------------------------------------------------------------------------
# API tests: EC_CEDULA & EC_RUC
# ---------------------------------------------------------------------------


def test_masks_valid_cedula_and_ignores_invalid(client):
    text = "Cédula válida 1710034065, inválida 1710034064, provincia 2510034065."
    data = _mask(client, text)

    assert "1710034065" not in data["masked"]
    assert "1710034064" in data["masked"]
    assert "2510034065" in data["masked"]
    assert [(e["label"], e["text"]) for e in data["entities"]] == [
        ("CEDULA", "1710034065")
    ]
    assert data["entities"][0]["token"].startswith("[CEDULA_")


def test_masks_all_valid_ruc_types_and_ignores_invalid(client):
    text = (
        "Natural 1710034065001, privada 1790010937001, pública 1760013210001, "
        "inválido 1710034065000 y malo 1790010938001."
    )
    data = _mask(client, text)

    for valid in ("1710034065001", "1790010937001", "1760013210001"):
        assert valid not in data["masked"]
    assert "1710034065000" in data["masked"]
    assert "1790010938001" in data["masked"]

    ruc_entities = [(e["label"], e["text"]) for e in data["entities"]]
    assert ruc_entities == [
        ("RUC", "1710034065001"),
        ("RUC", "1790010937001"),
        ("RUC", "1760013210001"),
    ]


# ---------------------------------------------------------------------------
# API tests: Cédula vs Phone disambiguation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        f"Mi cédula es {DUAL_VALID_CEDULA_PHONE}",
        f"Mi cedula: {DUAL_VALID_CEDULA_PHONE}",
        f"CI: {DUAL_VALID_CEDULA_PHONE}",
        f"Mi c.i. es {DUAL_VALID_CEDULA_PHONE}",
        f"Documento de identidad {DUAL_VALID_CEDULA_PHONE}",
        f"Número de documento {DUAL_VALID_CEDULA_PHONE}",
    ],
)
def test_cedula_keywords_beat_phone_on_dual_valid_number(client, text):
    data = _mask(client, text)
    assert DUAL_VALID_CEDULA_PHONE not in data["masked"]
    assert [(e["label"], e["text"]) for e in data["entities"]] == [
        ("CEDULA", DUAL_VALID_CEDULA_PHONE)
    ]


@pytest.mark.parametrize(
    "text",
    [
        f"Mi tel es {DUAL_VALID_CEDULA_PHONE}",
        f"Mi teléfono es {DUAL_VALID_CEDULA_PHONE}",
        f"Cel {DUAL_VALID_CEDULA_PHONE}",
        f"Celular: {DUAL_VALID_CEDULA_PHONE}",
        f"Móvil {DUAL_VALID_CEDULA_PHONE}",
        f"WhatsApp {DUAL_VALID_CEDULA_PHONE}",
        f"Mi número es +593 {DUAL_VALID_CEDULA_PHONE}",
    ],
)
def test_phone_keywords_beat_cedula_on_dual_valid_number(client, text):
    data = _mask(client, text)
    assert DUAL_VALID_CEDULA_PHONE not in data["masked"]
    phone_labels = [e["label"] for e in data["entities"]]
    assert phone_labels == ["PHONE"]


def test_cedula_and_phone_disambiguation_in_same_sentence_both_orders(client):
    d1 = _mask(client, f"tel {DUAL_VALID_CEDULA_PHONE}, mi cédula es {DUAL_VALID_CEDULA_PHONE}")
    assert [(e["label"], e["text"]) for e in d1["entities"]] == [
        ("PHONE", DUAL_VALID_CEDULA_PHONE),
        ("CEDULA", DUAL_VALID_CEDULA_PHONE),
    ]

    d2 = _mask(client, f"mi cédula es {DUAL_VALID_CEDULA_PHONE}, tel {DUAL_VALID_CEDULA_PHONE}")
    assert [(e["label"], e["text"]) for e in d2["entities"]] == [
        ("CEDULA", DUAL_VALID_CEDULA_PHONE),
        ("PHONE", DUAL_VALID_CEDULA_PHONE),
    ]


# ---------------------------------------------------------------------------
# API tests: BANK_ACCOUNT
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected_acct"),
    [
        ("Mi cuenta 2204589123 está activa", "2204589123"),
        ("Mi cta 40123456 de ahorros", "40123456"),
        ("Número de cuenta: 0012-3456-7890", "0012-3456-7890"),
        ("nro de cuenta es 2204589123", "2204589123"),
        ("IBAN: ES9121000418450200051332", "ES9121000418450200051332"),
    ],
)
def test_bank_account_masks_only_identifier_and_beats_phone(client, text, expected_acct):
    data = _mask(client, text)
    assert expected_acct not in data["masked"]
    assert [(e["label"], e["text"]) for e in data["entities"]] == [
        ("ACCOUNT", expected_acct)
    ]
    # Triggering keywords must stay intact in the masked output.
    prefix_word = text.split()[0]
    assert prefix_word in data["masked"]


def test_bank_account_ignores_monetary_amounts_durations_and_bad_lengths(client):
    text = (
        "Quiero depositar $5000 a 24 meses en mi cuenta por $1000000 "
        "o 500000 dólares; cta 12345 y cta 123456789012345678901."
    )
    data = _mask(client, text)
    assert data["masked"] == text
    assert data["entities"] == []


def test_bank_account_english_support(client):
    data = _mask(client, "My account number is 1234567890.", language="en")
    assert "1234567890" not in data["masked"]
    assert [(e["label"], e["text"]) for e in data["entities"]] == [
        ("ACCOUNT", "1234567890")
    ]


# ---------------------------------------------------------------------------
# API tests: SECRET_CREDENTIAL
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected_secret"),
    [
        ("mi clave es Secreta99, gracias", "Secreta99"),
        ("contraseña: P@ssw0rd!", "P@ssw0rd!"),
        ("contrasena=MiClave2026", "MiClave2026"),
        ("password: Tr0ub4dor&3", "Tr0ub4dor&3"),
        ("mi PIN es 4829.", "4829"),
        ("código de seguridad es 9384", "9384"),
        ("OTP: 847291", "847291"),
    ],
)
def test_secret_credential_masks_only_secret_token(client, text, expected_secret):
    data = _mask(client, text)
    assert expected_secret not in data["masked"]
    assert [(e["label"], e["text"]) for e in data["entities"]] == [
        ("SECRET", expected_secret)
    ]
    assert data["entities"][0]["token"].startswith("[SECRET_")


def test_secret_credential_ignores_non_secret_prose(client):
    text = "La contraseña es obligatoria, mi clave es incorrecta y olvidé mi pin."
    data = _mask(client, text)
    assert data["masked"] == text
    assert data["entities"] == []


# ---------------------------------------------------------------------------
# Unit & API tests: entities filtering
# ---------------------------------------------------------------------------


def test_resolve_entities_supports_canonical_and_label_aliases():
    assert resolve_entities(["person", "CEDULA", "EC_CEDULA", "ORG", "ACCOUNT", "SECRET"]) == [
        "PERSON",
        "EC_CEDULA",
        "ORGANIZATION",
        "BANK_ACCOUNT",
        "SECRET_CREDENTIAL",
    ]


def test_entities_filter_limits_detected_types(client):
    text = "Soy Juan Pérez, cédula 1710034065, tel 0991234567, email juan@coop.ec"
    data = _mask(client, text, entities=["CEDULA", "EMAIL"])

    assert "1710034065" not in data["masked"]
    assert "juan@coop.ec" not in data["masked"]
    # Unrequested entities remain untouched.
    assert "Juan Pérez" in data["masked"]
    assert "0991234567" in data["masked"]
    assert [e["label"] for e in data["entities"]] == ["CEDULA", "EMAIL"]


def test_entities_empty_list_masks_nothing(client):
    text = "Soy Juan Pérez, cédula 1710034065"
    data = _mask(client, text, entities=[])
    assert data["masked"] == text
    assert data["entities"] == []


def test_unknown_entity_returns_400(client):
    resp = client.post(
        "/mask",
        json={"text": "Hola", "language": "es", "entities": ["PERSON", "UNKNOWN_PII"]},
    )
    assert resp.status_code == 400
    assert "UNKNOWN_PII" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Unit & API tests: allow_list
# ---------------------------------------------------------------------------


def test_allow_list_unit_excludes_full_sub_and_super_overlapping_spans():
    text = "Quiero abrir Cuenta Ahorro Ordinario 2204589123 en Cooperativa San Cristóbal."
    allow_spans = _find_allow_list_spans(
        text,
        ["cuenta ahorro ordinario", "COOPERATIVA SAN CRISTÓBAL"],
    )
    assert len(allow_spans) == 2

    simulated = [
        # Full span matching allow_list phrase
        RecognizerResult(entity_type="ORGANIZATION", start=13, end=36, score=0.85),
        # Sub-span inside "Cuenta Ahorro Ordinario" ("Ahorro Ordinario")
        RecognizerResult(entity_type="PERSON", start=20, end=36, score=0.85),
        # Adjacent real PII NOT overlapping allow_list ("2204589123")
        RecognizerResult(entity_type="BANK_ACCOUNT", start=37, end=47, score=0.90),
        # Sub-span inside "Cooperativa San Cristóbal" ("San Cristóbal")
        RecognizerResult(entity_type="PERSON", start=63, end=76, score=0.85),
        # Super-span overlapping "Cooperativa San Cristóbal" ("en Cooperativa San Cristóbal")
        RecognizerResult(entity_type="ORGANIZATION", start=48, end=76, score=0.85),
    ]
    kept = _filter_allow_list(simulated, allow_spans)
    assert [(r.entity_type, text[r.start:r.end]) for r in kept] == [
        ("BANK_ACCOUNT", "2204589123")
    ]


def test_allow_list_prevents_masking_real_detected_entities_case_insensitively(client):
    text = "Trabajo en Banco Pichincha y mi contacto es Juan Pérez."
    without = _mask(client, text)
    assert "Banco Pichincha" not in without["masked"]
    assert "Juan Pérez" not in without["masked"]

    with_al = _mask(client, text, allow_list=["banco pichincha"])
    assert "Banco Pichincha" in with_al["masked"]
    assert "Juan Pérez" not in with_al["masked"]
    assert [(e["label"], e["text"]) for e in with_al["entities"]] == [
        ("PERSON", "Juan Pérez")
    ]


def test_allow_list_protects_domain_banking_phrases_while_masking_pii(client):
    domain_phrases = [
        "Cuenta Ahorro Ordinario",
        "Cooperativa San Cristóbal",
        "Ahorro Programado",
        "Hazte Socio Hoy",
        "Back to Back",
        "Socio AAA",
    ]
    text = (
        "Hola soy Juan Pérez, quiero información sobre Cuenta Ahorro Ordinario, "
        "Ahorro Programado, Hazte Socio Hoy, Back to Back y Socio AAA "
        "en Cooperativa San Cristóbal; mi cuenta es 2204589123."
    )
    data = _mask(client, text, allow_list=domain_phrases)

    for phrase in domain_phrases:
        assert phrase in data["masked"]
    assert "Juan Pérez" not in data["masked"]
    assert "2204589123" not in data["masked"]
    assert [(e["label"], e["text"]) for e in data["entities"]] == [
        ("PERSON", "Juan Pérez"),
        ("ACCOUNT", "2204589123"),
    ]


def test_allow_list_bounds_return_400(client):
    too_many = [f"phrase-{i}" for i in range(ALLOW_LIST_MAX_ITEMS + 1)]
    r1 = client.post("/mask", json={"text": "Hola", "language": "es", "allow_list": too_many})
    assert r1.status_code == 400

    too_long = ["x" * (ALLOW_LIST_MAX_ITEM_LEN + 1)]
    r2 = client.post("/mask", json={"text": "Hola", "language": "es", "allow_list": too_long})
    assert r2.status_code == 400


# ---------------------------------------------------------------------------
# API tests: Spanish names, false-positive suppression, & full banking sentence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected_name"),
    [
        ("Hola soy Juan Pérez, necesito información.", "Juan Pérez"),
        ("Hola, me llamo María José López", "María José López"),
        ("Mi nombre es María José López.", "María José López"),
        ("Soy María José López y quiero abrir una cuenta.", "María José López"),
        ("María José López", "María José López"),
        ("El pago lo hizo María José López.", "María José López"),
    ],
)
def test_real_spanish_names_detected_as_person_without_greeting_fp(client, text, expected_name):
    data = _mask(client, text)
    assert expected_name not in data["masked"]
    assert "Hola" in data["masked"] if "Hola" in text else True
    assert [(e["label"], e["text"]) for e in data["entities"]] == [
        ("PERSON", expected_name)
    ]


def test_spanish_banking_greetings_and_generic_products_not_masked(client):
    text = (
        "Hola, buenos días. Estimados, necesito información sobre Crédito Hipotecario, "
        "Crédito de Consumo, Depósito a Plazo Fijo, Ahorro Programado y Banca Móvil."
    )
    data = _mask(client, text)
    assert data["masked"] == text
    assert data["entities"] == []


def test_full_synthetic_banking_sentence_round_trip_and_one_way(client):
    allow_list = ["Cuenta Ahorro Ordinario", "Cooperativa San Cristóbal"]
    data = _mask(
        client,
        SYNTHETIC_BANKING_SENTENCE,
        language="es",
        allow_list=allow_list,
        return_entities=True,
    )

    assert [(e["label"], e["text"]) for e in data["entities"]] == [
        ("PERSON", "Juan Pérez"),
        ("CEDULA", "1710034065"),
        ("RUC", "1710034065001"),
        ("PHONE", "0991234567"),
        ("ACCOUNT", "2204589123"),
        ("SECRET", "Secreta99"),
    ]
    assert data["masked"].startswith("Hola soy [PERSON_")
    assert "Cuenta Ahorro Ordinario en Cooperativa San Cristóbal." in data["masked"]
    for raw in ("Juan Pérez", "1710034065", "1710034065001", "0991234567", "2204589123", "Secreta99"):
        assert raw not in data["masked"]

    # Restoration round-trip must reconstruct the exact source text.
    restored = data["masked"]
    for e in data["entities"]:
        assert SYNTHETIC_BANKING_SENTENCE[e["start"]:e["end"]] == e["text"]
        assert TOKEN_RE.fullmatch(e["token"])
        restored = restored.replace(e["token"], e["text"])
    assert restored == SYNTHETIC_BANKING_SENTENCE

    # return_entities=False must emit identical masked text and zero echoed PII.
    one_way = _mask(
        client,
        SYNTHETIC_BANKING_SENTENCE,
        language="es",
        allow_list=allow_list,
        return_entities=False,
    )
    assert one_way["masked"] == data["masked"]
    assert one_way["entities"] == []
    for raw in ("Juan Pérez", "1710034065", "1710034065001", "0991234567", "2204589123", "Secreta99"):
        assert raw not in str(one_way)


def test_backward_compatible_minimal_request_payload(client):
    """Existing callers (e.g. nimblersoft-bot) send only {"text": "..."}."""
    resp = client.post("/mask", json={"text": "Contact John Smith at john@acme.com"})
    assert resp.status_code == 200
    body = resp.json()
    assert "John Smith" not in body["masked"]
    assert "john@acme.com" not in body["masked"]
    assert {e["label"] for e in body["entities"]} >= {"PERSON", "EMAIL"}
