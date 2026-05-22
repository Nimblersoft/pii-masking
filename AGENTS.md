# PII Masking Microservice

## Overview

A small FastAPI service that detects and masks personally identifiable
information (PII) in free-form text before it is forwarded to an LLM or any
other downstream system.

Detection is powered by [Microsoft Presidio](https://microsoft.github.io/presidio/)
with spaCy NER. English and Spanish are supported out of the box.

## Purpose

LLM providers see whatever payloads you send them. To keep customer data out
of third-party logs and prompts, every user-supplied string is round-tripped
through `/mask` first. Entities (names, organizations, emails, phone numbers,
credit cards) are replaced with stable placeholder tokens like `[PERSON]`,
`[ORG]`, `[EMAIL]`, `[PHONE]`, `[CREDIT_CARD]`.

## Architecture

```
┌──────────────┐        ┌──────────────────┐        ┌──────────────────────┐
│  Any client  │──HTTP─▶│  pii-masking     │──▶ Presidio Analyzer          │
│  or service  │        │  (FastAPI :8090) │     (spaCy en + es)           │
└──────────────┘        │                  │──▶ Presidio Anonymizer        │
                        └────────┬─────────┘        └──────────────────────┘
                                 │
                                 ▼
                        ┌──────────────────┐
                        │ Token store      │
                        │ (in-memory,      │
                        │ SHA-256 hashed)  │
                        └──────────────────┘
```

Everything runs in a single container. Models and the analyzer/anonymizer
engines are loaded once at startup (warm-start) and reused per request.

## API Endpoints

| Method | Path             | Auth         | Purpose                              |
|--------|------------------|--------------|--------------------------------------|
| GET    | `/health`        | none         | Liveness + supported languages       |
| POST   | `/mask`          | X-API-Key*   | Mask PII in a text payload           |
| POST   | `/tokens`        | X-Master-Key | Create a new API token               |
| GET    | `/tokens`        | X-Master-Key | List active tokens (metadata only)   |
| DELETE | `/tokens/{id}`   | X-Master-Key | Revoke a token                       |

*`/mask` only requires `X-API-Key` when `REQUIRE_API_KEY=true`.

### `/mask` example

Request:
```json
{ "text": "Hi I'm John Smith from Acme Inc, email john@acme.com", "language": "en", "return_entities": true }
```

Response:
```json
{
  "masked": "Hi I'm [PERSON_3a7f1c08] from [ORG_b91e44d2], email [EMAIL_5c2a90ff]",
  "entities": [
    { "text": "John Smith",    "label": "PERSON", "token": "[PERSON_3a7f1c08]", "start": 7,  "end": 17 },
    { "text": "Acme Inc",      "label": "ORG",    "token": "[ORG_b91e44d2]",    "start": 23, "end": 31 },
    { "text": "john@acme.com", "label": "EMAIL",  "token": "[EMAIL_5c2a90ff]",  "start": 39, "end": 52 }
  ]
}
```

**Placeholder tokens** have the form `[TYPE_xxxxxxxx]`, where `xxxxxxxx` is the
first 8 hex chars of a salted SHA-256 of the original value. The same value
always maps to the same token (within and across requests, given a stable
`PII_HASH_SALT`), so a caller can send `masked` to an LLM and then **restore**
the original PII by replacing each `token` with its `text` from the `entities`
list. The hash is one-way; restoration relies on the returned mapping, not on
inverting the hash.

Set `return_entities: false` to receive only `masked` (no PII echoed back) when
restoration isn't needed.

### Entity mapping

| Presidio entity   | Output placeholder    |
|-------------------|-----------------------|
| `PERSON`          | `[PERSON_<hash>]`     |
| `ORGANIZATION`    | `[ORG_<hash>]`        |
| `EMAIL_ADDRESS`   | `[EMAIL_<hash>]`      |
| `PHONE_NUMBER`    | `[PHONE_<hash>]`      |
| `CREDIT_CARD`     | `[CREDIT_CARD_<hash>]`|

Overlapping detections are resolved by Presidio's default scoring (higher
confidence wins, ties broken by length).

## Token Auth

- **Master key** (`PII_MASTER_KEY`): controls the `/tokens` admin surface.
  Auto-generated as a random 32-char hex string on first boot if not set.
  The generated key is logged once to stdout — capture it from container
  logs (`docker logs pii-masking`) if you didn't supply one.
- **API tokens** (`X-API-Key`): format `pii_<40 hex chars>`. Generated via
  `POST /tokens`. **Plain values are returned exactly once.** Internally
  only the SHA-256 hash is stored.
- **In-memory storage**: tokens are ephemeral and lost on container restart.
  This is intentional — regenerate via the CLI after each restart.
- **`REQUIRE_API_KEY`** (default `false`): when `true`, every `/mask`
  request must present a valid `X-API-Key`. Suitable for multi-tenant or
  externally reachable deployments.

### CLI

```bash
export PII_MASTER_KEY=...   # or pass --master-key
python cli.py generate
python cli.py list
python cli.py revoke <token-id>
```

Optional flags: `--url http://host:port` (defaults to `http://localhost:8090`).

## Build & Run

```bash
cd pii-masking
docker compose up -d --build
curl -s http://localhost:8090/health
```

The first build downloads the spaCy English + Spanish models (~50 MB total).

### Environment variables

| Variable               | Default       | Notes                                              |
|------------------------|---------------|----------------------------------------------------|
| `PORT`                 | `8090`        | Bind port                                          |
| `PII_MASTER_KEY`       | autogenerated | Admin auth for `/tokens`                           |
| `PII_HASH_SALT`        | autogenerated | Salt for placeholder-token hashing. Set a stable value for consistent tokens across restarts |
| `REQUIRE_API_KEY`      | `false`       | If `true`, `/mask` requires `X-API-Key`            |
| `INFISICAL_PROJECT_ID` | —             | Fetch secrets from Infisical at startup            |
| `INFISICAL_API_URL`    | `https://app.infisical.com` | Infisical server URL                 |
| `INFISICAL_ENVIRONMENT`| `dev`         | Infisical environment slug to fetch secrets from   |
| `INFISICAL_CLIENT_ID`  | —             | Infisical machine identity client ID               |
| `INFISICAL_CLIENT_SECRET` | —          | Infisical machine identity client secret           |

## Infisical Integration

When `INFISICAL_PROJECT_ID` and Infisical credentials are present, `entrypoint.sh`
fetches secrets from Infisical before starting the server. `PII_MASTER_KEY` is
the primary secret managed this way. If credentials are absent the service falls
back to whatever env vars are set (or auto-generates the master key).

To rotate the key: update the secret in Infisical and restart the container.

## Cloudflare Tunnel Notes

This service is intended to live on an internal network and has no public
ingress. If you ever need to expose it for debugging, prefer a private hostname
with access controls rather than a public route.

## Security Posture

- Runs as non-root `appuser` (uid 1001).
- `no-new-privileges:true` applied via compose.
- API tokens are SHA-256 hashed at rest; raw values are returned once on
  creation and never persisted.
- Master key is auto-generated if absent so the admin surface is never
  silently unauthenticated.
- `/health` is intentionally unauthenticated for orchestrator probes.
- No secrets committed to the repo or baked into the image.
