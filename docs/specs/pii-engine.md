---
title: "Spec: PII Engine"
type: spec
status: active
covers: app/pii_engine.py, app/recognizers.py
last_checked: 2026-11-19
---

# PII Engine — Behavioral Contract

Modules: `app/pii_engine.py` · `app/recognizers.py` · Presidio AnalyzerEngine +
AnonymizerEngine over spaCy NER and custom financial/identity recognizers,
wrapped as a warm-started process-wide singleton.

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
  `ORG`/`ORGANIZATION`→ORGANIZATION, `NORP`→NRP,
  `GPE`/`LOC`/`FAC`/`LOCATION`→LOCATION, `DATE`/`TIME`→DATE_TIME.
  `MISC` is intentionally left unmapped so `es_core_news_sm` does not
  misclassify Spanish banking product titles or prose as `ORGANIZATION`.
- `low_confidence_score_multiplier: 0.4` — NER labels classified as
  low-confidence get their score multiplied by 0.4 before Presidio's
  decision policy runs.
- `low_score_entity_names: []` — no entity class is pre-designated low-score.

`SUPPORTED_LANGUAGES = ["en", "es"]` is the single source of truth; requests
with any other language raise `ValueError` (→ HTTP 400 in `app/main.py`).

## Recognizers

Default `SpacyRecognizer` and `PhoneRecognizer` entries are replaced per
language in `PIIEngine.__init__`:

- **NER (`PERSON`, `ORGANIZATION`)**:
  - `en`: `SpacyRecognizer(supported_entities=["PERSON", "ORGANIZATION"])`.
  - `es`: `SpanishFilteredSpacyRecognizer` trims polluted leading introducers
    (e.g. `Soy `, `Hola `), suppresses greetings/sentence-initial verbs/generic
    banking product false positives, and strips non-noun single-token `PERSON`
    misdetections. `SpanishPersonContextRecognizer` supplements `es_core_news_sm`
    for Spanish names after explicit introducer cues (`me llamo`, `mi nombre es`,
    `soy`, `titular:`, etc.) and rescues multi-word Title-Case Spanish names
    mis-tagged as `MISC` (e.g. `"María José López"`).
- **Phone (`PHONE_NUMBER`)**: `PhoneRecognizer` configured with regional
  support including `EC` and `ES` alongside Presidio defaults, with Spanish
  phone context words (`tel`, `teléfono`, `cel`, `celular`, `móvil`, `whatsapp`,
  etc.) for `es`.
- **Built-in Presidio recognizers** cover `EMAIL_ADDRESS` and `CREDIT_CARD`.
- **Custom recognizers (`app/recognizers.py`)**, registered for `es` and `en`:
  - `EcCedulaRecognizer` (`EC_CEDULA`): 10-digit Ecuadorian cédula with strict
    province (`01..24` or `30`), 3rd digit `0..5`, and modulo-10 check digit.
    Clause-local context disambiguates against `PHONE_NUMBER`: cédula keywords
    (`cédula`, `cedula`, `ci`, `c.i.`, `identidad`, `documento`) boost to `0.92`;
    explicit phone keywords (`tel`, `teléfono`, `cel`, `celular`, `móvil`,
    `whatsapp`, `+593`) defer so `PHONE_NUMBER` wins; account keywords demote
    below `BANK_ACCOUNT`.
  - `EcRucRecognizer` (`EC_RUC`): 13-digit Ecuadorian RUC validating province
    (`01..24` or `30`), establishment suffix `001..999`, and natural-person
    (mod-10, 3rd digit `0..5`), private-entity (mod-11, 3rd digit `9`), or
    public-entity (mod-11, 3rd digit `6`, 10th digit `0`) check digits.
  - `BankAccountRecognizer` (`BANK_ACCOUNT`): contextual recognizer for
    bank/coop account triggers (`cuenta`, `cta`, `número de cuenta`,
    `nro de cuenta`, `iban`, English `account`) followed by 6–20 digit account
    identifiers (or IBANs). Emits only the account identifier span (`score=0.90`,
    beating `PHONE_NUMBER`) and rejects monetary amounts (`$5000`, `USD`,
    `dólares`) and durations (`24 meses`).
  - `SecretCredentialRecognizer` (`SECRET_CREDENTIAL`): contextual recognizer
    for passwords, PINs, security codes, and OTPs (`clave`, `contraseña`,
    `contrasena`, `password`, `pin`, `código de seguridad`, `otp`) followed by
    `es`/`is`/`:`/`=`. Emits only the secret token span (`score=0.95`, beating
    NER) and ignores plain prose adjectives (e.g. `"la contraseña es obligatoria"`).

## Entity surface, filtering, and allow-list

`mask(text, language="en", entities=None, allow_list=None)` runs all
`SUPPORTED_ENTITIES` when `entities` is `None`:

| Presidio entity | Output label / token prefix |
|---|---|
| `PERSON` | `PERSON` |
| `ORGANIZATION` | `ORG` |
| `EMAIL_ADDRESS` | `EMAIL` |
| `PHONE_NUMBER` | `PHONE` |
| `CREDIT_CARD` | `CREDIT_CARD` |
| `EC_CEDULA` | `CEDULA` |
| `EC_RUC` | `RUC` |
| `BANK_ACCOUNT` | `ACCOUNT` |
| `SECRET_CREDENTIAL` | `SECRET` |

- **`entities` filter**: accepts canonical Presidio entity names or output
  labels (case-insensitive, deduplicated). Any unknown entry raises `ValueError`
  (→ HTTP 400). An explicit empty list `[]` masks nothing.
- **`allow_list` filter**: optional case-insensitive list of domain phrases
  that must never be masked (max 100 items, max 120 chars each; violations
  raise `ValueError` → HTTP 400). Word-bounded matches are computed against the
  source text and applied before overlap resolution; any candidate entity span
  overlapping an allow-listed span (full, sub-span, or super-span) is excluded.
- **Overlap resolution**: `_resolve_overlaps()` resolves cross-entity overlaps
  deterministically (higher confidence wins, ties broken by longer span, then
  earlier start) before calling `AnonymizerEngine.anonymize(...,
  merge_entities_with_spaces=False)`, keeping `masked` and `entities` strictly
  1-to-1.

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
