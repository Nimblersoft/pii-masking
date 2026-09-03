---
title: "Spec: PII Engine"
type: spec
status: active
covers: app/pii_engine.py
last_checked: 2026-09-03
---

# PII Engine — Behavioral Contract

Module: `app/pii_engine.py` · Presidio AnalyzerEngine + AnonymizerEngine over
spaCy NER, wrapped as a warm-started process-wide singleton.

## Responsibilities

1. Detect PII entities in text (`en` / `es`) with Presidio.
2. Replace every detected span with a deterministic placeholder token
   `[TYPE_xxxxxxxx]` (token derivation is specified in
   [ADR 0001](../adr/0001-hash-token-reversible-masking.md)).
3. Return the masked text plus a per-entity mapping (`text`, `label`,
   `token`, `start`, `end`) the caller uses for restoration.

## Initialization (warm start)

- `get_engine()` lazily constructs the singleton; `warm_start()` constructs it
  **and** runs one `mask("warmup", lang)` per supported language so spaCy
  models are fully loaded before the first real request. `app/main.py`'s
  lifespan calls `warm_start()` at process start; tests do the same via
  `TestClient` context manager.
- Analyzer and anonymizer engines are built once and reused per request —
  never per-call construction.

## Language & NLP engine configuration

| Language | spaCy model | Notes |
|---|---|---|
| `en` | `en_core_web_sm` 3.8.0 | Downloaded in the Dockerfile |
| `es` | `es_core_news_sm` 3.8.0 | Downloaded in the Dockerfile |

Both models are loaded into one spaCy NLP engine via
`NlpEngineProvider` with this NER configuration:

- `labels_to_ignore: ["O"]`
- `model_to_presidio_entity_mapping`: `PER`/`PERSON`→PERSON,
  `ORG`/`ORGANIZATION`/`MISC`→ORGANIZATION, `NORP`→NRP,
  `GPE`/`LOC`/`FAC`/`LOCATION`→LOCATION, `DATE`/`TIME`→DATE_TIME
- `low_confidence_score_multiplier: 0.4` — NER labels classified as
  low-confidence get their score multiplied by 0.4 before Presidio's
  decision policy runs.
- `low_score_entity_names: []` — no entity class is pre-designated low-score.

`SUPPORTED_LANGUAGES = ["en", "es"]` is the single source of truth; requests
with any other language raise `ValueError` (→ HTTP 400 in `app/main.py`).

## Recognizers

- **SpacyRecognizer** is explicitly registered once per language, restricted
  to `supported_entities=["PERSON", "ORGANIZATION"]` — NER only contributes
  those two entity types to results.
- **Built-in Presidio recognizers** (registered by `AnalyzerEngine` defaults)
  cover the rest of the surface: email, phone, credit card, and other
  patterns, including `phonenumbers`-backed phone detection.
- **No custom locale recognizers exist yet** (e.g. Ecuadorian cédula or
  local phone formats). Adding one means implementing a Presidio
  `PatternRecognizer`/`EntityRecognizer` and registering it on
  `self.analyzer.registry` in `PIIEngine.__init__`; extend this spec and the
  entity map in the same change.

## Entity surface

`analyze()` is always called with `entities=SUPPORTED_ENTITIES`:

| Presidio entity | Output label / token prefix |
|---|---|
| `PERSON` | `PERSON` |
| `ORGANIZATION` | `ORG` |
| `EMAIL_ADDRESS` | `EMAIL` |
| `PHONE_NUMBER` | `PHONE` |
| `CREDIT_CARD` | `CREDIT_CARD` |

Overlapping detections are resolved by Presidio's default decision policy
(higher confidence wins, ties broken by span length) — no custom
`decision_process` is configured.

## Anonymization

- One custom `OperatorConfig("custom", {"lambda": …})` per entity type. The
  lambda only receives the matched value, so entity type and salt are bound
  per-operator via default arguments (`lambda v, e=entity, s=salt`) to keep
  tokens type-labelled and consistent.
- Token: `[{LABEL}_{first 8 hex of SHA-256(salt + value)}]`
  (`TOKEN_HASH_HEX_LEN = 8`).

## Salt handling

`PII_HASH_SALT` env var if set (stripped, non-empty); otherwise an ephemeral
`secrets.token_hex(16)` salt is generated and a warning is logged — tokens
will **not** survive restarts. Stable cross-restart tokens therefore require
Infisical/env to provide the salt (see the
[Infisical runbook](../runbooks/infisical-integration.md)).

## Guarantees

- Same value + same salt → same token, within a request, across requests,
  and across restarts (given a stable salt).
- Offsets in `entities` index the **original** text; `entities` is sorted by
  `start`.
- The masked output contains no raw PII from detected spans; restoration is
  caller-side via the returned mapping.
