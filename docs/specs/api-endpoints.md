---
title: "Spec: API Endpoints"
type: spec
status: active
covers: app/main.py
last_checked: 2026-09-03
---

# API Endpoints — Behavioral Contract

Module: `app/main.py` · FastAPI application, Pydantic v2 request/response
models, header-based auth.

## Routes

| Method | Path | Auth | Handler | Success | Errors |
|---|---|---|---|---|---|
| GET | `/health` | none | `health` | 200 `HealthResponse` | — |
| POST | `/mask` | `X-API-Key`* | `mask` | 200 `MaskResponse` | 400, 401 |
| POST | `/tokens` | `X-Master-Key` | `create_token` | 200 `TokenCreateResponse` | 401 |
| GET | `/tokens` | `X-Master-Key` | `list_tokens` | 200 `TokenListResponse` | 401 |
| DELETE | `/tokens/{token_id}` | `X-Master-Key` | `revoke_token` | 200 `RevokeResponse` | 401, 404 |

*`/mask` auth is only enforced when `REQUIRE_API_KEY=true`.

## Models

- `MaskRequest` — `text: str` (required), `language: str = "en"`,
  `return_entities: bool = true` (set false to receive only `masked` and
  avoid echoing PII back).
- `EntitySpan` — `text`, `label`, `token`, `start`, `end` (offsets index the
  original text).
- `MaskResponse` — `masked: str`, `entities: list[EntitySpan]` (empty when
  `return_entities=false`).
- `HealthResponse` — `status: "ok"`, `models: ["en","es"]`.
- `TokenCreateResponse` — `token` (raw, shown once), `id`, `created_at`.
- `TokenInfo` — `id`, `prefix`, `created_at`, `last_used?`.
- `TokenListResponse` — `tokens: list[TokenInfo]`.
- `RevokeResponse` — `status: "revoked"`.

## Authentication

- `require_api_key` (dependency of `/mask`): no-op unless the store enforces
  keys. Accepts `X-API-Key: <token>` or, as fallback,
  `Authorization: Bearer <token>`. Verification is hash-lookup in the token
  store.
- `require_master_key` (dependency of the `/tokens` surface): compares
  `X-Master-Key` against the store's master key in constant time.
- Failures raise FastAPI `HTTPException`; error bodies use the framework
  default schema `{"detail": "<message>"}` for all non-2xx responses.

## Error behavior

- Unsupported `language` → `ValueError` from the engine → **400** with the
  engine's message.
- Missing/invalid credentials → **401** `Invalid or missing API key` /
  `Invalid or missing X-Master-Key`.
- Revoking an unknown token id → **404** `Token not found`.

## Lifespan

On startup: seed `PII_API_TOKEN` (if set) into the token store, then
`warm_start()` the PII engine (see the [PII engine spec](pii-engine.md)).
The [CLI](../../cli.py) drives `POST/GET/DELETE /tokens` with
`X-Master-Key`; the `./cli` wrapper reads the key from the running
container.
