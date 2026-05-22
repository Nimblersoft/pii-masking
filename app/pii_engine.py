from __future__ import annotations

import hashlib
import os
import secrets

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_analyzer.predefined_recognizers import SpacyRecognizer
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig, RecognizerResult

SUPPORTED_LANGUAGES = ["en", "es"]

ENTITY_LABEL_MAP: dict[str, str] = {
    "PERSON": "PERSON",
    "ORGANIZATION": "ORG",
    "EMAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER": "PHONE",
    "CREDIT_CARD": "CREDIT_CARD",
}

SUPPORTED_ENTITIES: list[str] = list(ENTITY_LABEL_MAP.keys())

TOKEN_HASH_HEX_LEN = 8


def _load_or_generate_salt() -> str:
    salt = os.environ.get("PII_HASH_SALT", "").strip()
    if salt:
        return salt
    generated = secrets.token_hex(16)
    print(
        "[pii_engine] PII_HASH_SALT not set — generated ephemeral salt. "
        "Placeholder tokens will NOT be consistent across restarts.",
        flush=True,
    )
    return generated


def _token(value: str, entity_type: str, salt: str) -> str:
    """Deterministic, salted, one-way placeholder token for a PII value.

    Same value + same salt → same token, so a caller can map tokens back to
    originals via the returned entities list (the hash itself is irreversible).
    """
    label = ENTITY_LABEL_MAP.get(entity_type, entity_type)
    digest = hashlib.sha256((salt + value).encode("utf-8")).hexdigest()[:TOKEN_HASH_HEX_LEN]
    return f"[{label}_{digest}]"


def _build_operators(salt: str) -> dict[str, OperatorConfig]:
    # The custom lambda only receives the matched value, so bind entity_type and
    # salt per entry to embed the type label and keep tokens consistent.
    return {
        entity: OperatorConfig(
            "custom",
            {"lambda": lambda v, e=entity, s=salt: _token(v, e, s)},
        )
        for entity in ENTITY_LABEL_MAP
    }


def _build_nlp_engine():
    provider = NlpEngineProvider(
        nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [
                {"lang_code": "en", "model_name": "en_core_web_sm"},
                {"lang_code": "es", "model_name": "es_core_news_sm"},
            ],
            "ner_model_configuration": {
                "labels_to_ignore": ["O"],
                "model_to_presidio_entity_mapping": {
                    "PER": "PERSON",
                    "PERSON": "PERSON",
                    "NORP": "NRP",
                    "FAC": "LOCATION",
                    "LOC": "LOCATION",
                    "GPE": "LOCATION",
                    "LOCATION": "LOCATION",
                    "ORG": "ORGANIZATION",
                    "ORGANIZATION": "ORGANIZATION",
                    "MISC": "ORGANIZATION",
                    "DATE": "DATE_TIME",
                    "TIME": "DATE_TIME",
                },
                "low_score_entity_names": [],
                "low_confidence_score_multiplier": 0.4,
            },
        }
    )
    return provider.create_engine()


class PIIEngine:
    def __init__(self) -> None:
        self.salt = _load_or_generate_salt()
        self.operators = _build_operators(self.salt)
        nlp_engine = _build_nlp_engine()
        self.analyzer = AnalyzerEngine(
            nlp_engine=nlp_engine,
            supported_languages=SUPPORTED_LANGUAGES,
        )
        for lang in SUPPORTED_LANGUAGES:
            self.analyzer.registry.add_recognizer(
                SpacyRecognizer(
                    supported_language=lang,
                    supported_entities=["PERSON", "ORGANIZATION"],
                )
            )
        self.anonymizer = AnonymizerEngine()

    def mask(self, text: str, language: str = "en") -> dict:
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"Unsupported language '{language}'. Supported: {SUPPORTED_LANGUAGES}"
            )

        results: list[RecognizerResult] = self.analyzer.analyze(
            text=text,
            language=language,
            entities=SUPPORTED_ENTITIES,
        )

        anonymized = self.anonymizer.anonymize(
            text=text,
            analyzer_results=results,
            operators=self.operators,
        )

        entities = [
            {
                "text": text[r.start:r.end],
                "label": ENTITY_LABEL_MAP.get(r.entity_type, r.entity_type),
                "token": _token(text[r.start:r.end], r.entity_type, self.salt),
                "start": r.start,
                "end": r.end,
            }
            for r in sorted(results, key=lambda x: x.start)
        ]

        return {"masked": anonymized.text, "entities": entities}


_engine: PIIEngine | None = None


def get_engine() -> PIIEngine:
    global _engine
    if _engine is None:
        _engine = PIIEngine()
    return _engine


def warm_start() -> PIIEngine:
    engine = get_engine()
    for lang in SUPPORTED_LANGUAGES:
        engine.mask("warmup", language=lang)
    return engine
