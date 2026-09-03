---
title: "PII Masking — Documentation Index"
type: index
status: active
confidence: strong
tags:
  - index
last_checked: 2026-09-03
---

# PII Masking — Documentation

FastAPI microservice that detects and masks PII (names, organizations,
emails, phone numbers, credit cards) in free-form text via Microsoft
Presidio + spaCy (English and Spanish), replacing each value with a
deterministic salted placeholder token (`[PERSON_3a7f1c08]`) before the text
is sent to an LLM or any third party. Agent working context lives in
[AGENTS.md](../AGENTS.md); domain terminology in [CONTEXT.md](../CONTEXT.md).

**Active versions** (verified green against the full test suite,
2026-09-03 — see `requirements.txt` for the authoritative pins):

| Component | Version |
|---|---|
| Python | 3.11 |
| FastAPI / Pydantic / Uvicorn | 0.141.1 / 2.13.5 / 0.52.4 |
| spaCy (thinc pinned `<8.4.0`) | 3.8.14 (thinc 8.3.13) |
| Presidio analyzer + anonymizer (co-versioned) | 2.2.364 |
| spaCy models | `en_core_web_sm` 3.8.0, `es_core_news_sm` 3.8.0 |

**Core principles**

- **Zero-Trust egress** — no payload leaves for an LLM without passing
  through `/mask`; the provider only ever sees placeholder tokens.
- **Deterministic surrogate hashing** — same value + stable `PII_HASH_SALT`
  → same token, within and across requests (ADR 0001). The hash is one-way;
  restoration is caller-side via the returned `entities` map.
- **Runtime secret injection** — `PII_MASTER_KEY`, `PII_HASH_SALT`, and
  `PII_API_TOKEN` are fetched from Infisical at container start; no
  unencrypted `.env` on disk.
- **Privacy-regulation alignment (LOPDP and similar)** — minimize PII
  exposure to third parties by design; keep PII↔token mapping out of the
  service.

## Document map

| Folder | Contains | Answers |
|---|---|---|
| [`adr/`](adr/) | Architectural Decision Records | *Why is it built this way?* |
| [`specs/`](specs/) | Module contracts (one per code module) | *What must this module do?* |
| [`architecture/`](architecture/) | Topology, threat model, data flow | *What is wired to what?* |
| [`runbooks/`](runbooks/) | Exact command sequences | *What do I run to do X?* |

Filing rules and frontmatter schemas are SSOT in
[`docs-organization-blueprint.md`](docs-organization-blueprint.md) — consult
§3 when a document's home is ambiguous, and apply the frontmatter from §4.

## Decisions

- [ADR 0001 — Reversible masking via salted hash tokens](adr/0001-hash-token-reversible-masking.md)

## Specs

- [PII Engine](specs/pii-engine.md) — covers `app/pii_engine.py`
- [Token Store](specs/token-store.md) — covers `app/token_store.py`
- [API Endpoints](specs/api-endpoints.md) — covers `app/main.py`

## Runbooks

- [Local Development](runbooks/local-development.md) — venv bootstrap, models, tests
- [Docker Deployment](runbooks/docker-deployment.md) — build, compose, health probes
- [Infisical Integration](runbooks/infisical-integration.md) — runtime secret injection

## Architecture

- [Zero-Trust AI Perimeter](architecture/zero-trust-ai-perimeter.md) — end-to-end
  data flow, Infisical secret path, threat model
