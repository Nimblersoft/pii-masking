---
title: "Spec: Token Store"
type: spec
status: active
covers: app/token_store.py
last_checked: 2026-09-03
---

# Token Store — Behavioral Contract

Module: `app/token_store.py` · In-memory store for **API tokens** (client
credentials for `/mask`) plus master-key handling.

> **Naming:** this module has nothing to do with Placeholder Tokens
> (`[PERSON_3a7f1c08]`), which are computed statelessly in
> [`app/pii_engine.py`](pii-engine.md). See [CONTEXT.md](../../CONTEXT.md)
> for the flagged ambiguity.

## API token lifecycle

- **Format:** `pii_` + 40 hex chars (`secrets.token_hex(20)`), e.g.
  `pii_<40 hex>`. A stored "prefix" (`pii_` + first 2 chars) is the only
  fragment ever shown in listings.
- **Creation (`create_token`):** generates the raw value, stores a
  SHA-256 hash (never the raw), UUID id, `created_at`, `last_used=None`.
  The raw value is returned to the caller **exactly once** — there is no
  way to retrieve it afterwards.
- **Verification (`verify_token`):** SHA-256 the presented value, look it up
  in the hash→id index; on success stamp `last_used` (UTC ISO-8601).
- **Listing (`list_tokens`):** metadata only — `id`, `prefix`, `created_at`,
  `last_used`. Raw values and hashes are never exposed.
- **Revocation (`revoke`):** removes by id; `False` if unknown (→ HTTP 404).
- **Seeding (`seed_token`):** idempotently registers a pre-existing raw token
  (e.g. `PII_API_TOKEN` from Infisical, seeded in `app/main.py`'s lifespan so
  the container self-provisions on restart).

## Storage model

- Plain in-memory dicts guarded by an `threading.RLock`:
  `_tokens: {id → record}` and `_hash_to_id: {sha256 → id}`.
- **No TTL, no persistence** — intentional. All tokens are lost on restart;
  callers re-seed via `PII_API_TOKEN` or regenerate via the CLI
  (`python cli.py generate`). Introducing TTL or persistence would be a new
  ADR.
- Singleton via `get_store()`; tests rebuild the singleton
  (`reset_store` fixture) so env changes take effect.

## Master key

- Source: `PII_MASTER_KEY` env var; if absent, a 32-hex-char key is
  generated, written back to the process env, and **logged once to stdout**
  (capture from `docker logs pii-masking`). The admin surface is therefore
  never silently unauthenticated.
- `verify_master_key` uses `secrets.compare_digest` (constant-time).

## Enforcement flag

`REQUIRE_API_KEY` is read once at store construction
(`"true"` → enforce). When enforced, `/mask` requires a valid API token
(`X-API-Key` or `Authorization: Bearer`); see the
[API endpoints spec](api-endpoints.md).
