# Spec: docs/specs/pii-engine.md
from __future__ import annotations

import hashlib
import os
import re
import secrets

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_analyzer.predefined_recognizers import SpacyRecognizer
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig, RecognizerResult

from app.recognizers import (
    SpanishFilteredSpacyRecognizer,
    build_custom_recognizers,
    build_phone_recognizer,
)

SUPPORTED_LANGUAGES = ["en", "es"]

ENTITY_LABEL_MAP: dict[str, str] = {
    "PERSON": "PERSON",
    "ORGANIZATION": "ORG",
    "EMAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER": "PHONE",
    "CREDIT_CARD": "CREDIT_CARD",
    "EC_CEDULA": "CEDULA",
    "EC_RUC": "RUC",
    "BANK_ACCOUNT": "ACCOUNT",
    "SECRET_CREDENTIAL": "SECRET",
}

SUPPORTED_ENTITIES: list[str] = list(ENTITY_LABEL_MAP.keys())

# Accepts either canonical Presidio entity names or output labels (case-insensitive).
ENTITY_ALIASES: dict[str, str] = {
    **{entity: entity for entity in ENTITY_LABEL_MAP},
    **{label: entity for entity, label in ENTITY_LABEL_MAP.items()},
}

ALLOW_LIST_MAX_ITEMS = 100
ALLOW_LIST_MAX_ITEM_LEN = 120

TOKEN_HASH_HEX_LEN = 8


def resolve_entities(entities: list[str] | None) -> list[str]:
    """Validate and normalize requested entities (canonical names or output labels)."""
    if entities is None:
        return list(SUPPORTED_ENTITIES)

    resolved: list[str] = []
    seen: set[str] = set()
    for raw in entities:
        key = raw.strip().upper()
        canonical = ENTITY_ALIASES.get(key)
        if canonical is None:
            raise ValueError(
                f"Unsupported entity '{raw}'. Supported: {SUPPORTED_ENTITIES} "
                f"(labels: {sorted(set(ENTITY_LABEL_MAP.values()))})"
            )
        if canonical not in seen:
            seen.add(canonical)
            resolved.append(canonical)
    return resolved


def _find_allow_list_spans(text: str, allow_list: list[str] | None) -> list[tuple[int, int]]:
    """Validate allow_list bounds and return case-insensitive matched spans in text."""
    if allow_list is None:
        return []
    if len(allow_list) > ALLOW_LIST_MAX_ITEMS:
        raise ValueError(
            f"allow_list exceeds maximum of {ALLOW_LIST_MAX_ITEMS} items"
        )

    spans: list[tuple[int, int]] = []
    for item in allow_list:
        if len(item) > ALLOW_LIST_MAX_ITEM_LEN:
            raise ValueError(
                f"allow_list item exceeds maximum length of {ALLOW_LIST_MAX_ITEM_LEN} characters"
            )
        cleaned = item.strip()
        if not cleaned or not text:
            continue
        core = r"\s+".join(re.escape(part) for part in cleaned.split())
        prefix = r"(?<!\w)" if (cleaned[0].isalnum() or cleaned[0] == "_") else ""
        suffix = r"(?!\w)" if (cleaned[-1].isalnum() or cleaned[-1] == "_") else ""
        pattern = re.compile(f"{prefix}{core}{suffix}", re.IGNORECASE)
        for match in pattern.finditer(text):
            spans.append((match.start(), match.end()))
    return spans


def _filter_allow_list(
    results: list[RecognizerResult],
    allow_spans: list[tuple[int, int]],
) -> list[RecognizerResult]:
    """Exclude any detected span that overlaps an allow-listed phrase span."""
    if not allow_spans:
        return results
    return [
        r
        for r in results
        if not any(r.start < al_end and r.end > al_start for al_start, al_end in allow_spans)
    ]


def _resolve_overlaps(results: list[RecognizerResult]) -> list[RecognizerResult]:
    """Resolve overlapping spans: higher confidence wins, ties broken by longer span."""
    ordered = sorted(
        results,
        key=lambda r: (-r.score, -(r.end - r.start), r.start),
    )
    selected: list[RecognizerResult] = []
    for candidate in ordered:
        if any(candidate.start < kept.end and candidate.end > kept.start for kept in selected):
            continue
        selected.append(candidate)
    selected.sort(key=lambda r: r.start)
    return selected


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
            self.analyzer.registry.remove_recognizer("SpacyRecognizer", language=lang)
            self.analyzer.registry.remove_recognizer("PhoneRecognizer", language=lang)
            if lang == "es":
                self.analyzer.registry.add_recognizer(
                    SpanishFilteredSpacyRecognizer(
                        supported_entities=["PERSON", "ORGANIZATION"],
                    )
                )
            else:
                self.analyzer.registry.add_recognizer(
                    SpacyRecognizer(
                        supported_language=lang,
                        supported_entities=["PERSON", "ORGANIZATION"],
                    )
                )
            self.analyzer.registry.add_recognizer(build_phone_recognizer(lang))
            for recognizer in build_custom_recognizers(lang):
                self.analyzer.registry.add_recognizer(recognizer)
        self.anonymizer = AnonymizerEngine()

    def mask(
        self,
        text: str,
        language: str = "en",
        entities: list[str] | None = None,
        allow_list: list[str] | None = None,
    ) -> dict:
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"Unsupported language '{language}'. Supported: {SUPPORTED_LANGUAGES}"
            )

        target_entities = resolve_entities(entities)
        allow_spans = _find_allow_list_spans(text, allow_list)

        if not text or not target_entities:
            return {"masked": text, "entities": []}

        results: list[RecognizerResult] = self.analyzer.analyze(
            text=text,
            language=language,
            entities=target_entities,
        )
        results = _filter_allow_list(results, allow_spans)
        results = _resolve_overlaps(results)

        anonymized = self.anonymizer.anonymize(
            text=text,
            analyzer_results=results,
            operators=self.operators,
            merge_entities_with_spaces=False,
        )

        entity_spans = [
            {
                "text": text[r.start:r.end],
                "label": ENTITY_LABEL_MAP.get(r.entity_type, r.entity_type),
                "token": _token(text[r.start:r.end], r.entity_type, self.salt),
                "start": r.start,
                "end": r.end,
            }
            for r in results
        ]

        return {"masked": anonymized.text, "entities": entity_spans}


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
