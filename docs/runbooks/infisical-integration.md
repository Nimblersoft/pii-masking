---
title: "Runbook: Infisical Integration"
type: runbook
status: active
confidence: strong
tags:
  - runbook
  - infisical
  - secrets
last_checked: 2026-09-03
---

# Infisical Integration — Runtime Secret Injection

`entrypoint.sh` fetches secrets from Infisical via Universal Auth before
starting uvicorn, so no unencrypted `.env` lives on disk inside the
container.

## Secrets managed

| Key | Purpose |
|---|---|
| `PII_MASTER_KEY` | Admin auth for `/tokens` (primary secret managed here) |
| `PII_HASH_SALT` | Stable placeholder tokens across restarts — **treat as a secret** (ADR 0001) |
| `PII_API_TOKEN` | Pre-provisioned API token, seeded into the store at every boot |

## One-time setup

1. In Infisical, create a **Machine Identity** with Universal Auth
   (client ID + secret) and grant it read access to the PII Masking
   project + environment (default `dev`).
2. Add the secrets above to that project/environment.
3. Give the host environment the machine credentials (e.g. shell profile,
   host secret store, or compose `.env` — gitignored):

```bash
export INFISICAL_PROJECT_ID=<workspace id>
export INFISICAL_CLIENT_ID=<machine identity client id>
export INFISICAL_CLIENT_SECRET=<machine identity secret>
# Optional overrides:
export INFISICAL_ENVIRONMENT=dev
export INFISICAL_API_URL=https://app.infisical.com   # or http://infisical-backend:8080 via the shared docker network
```

## Runtime flow (what entrypoint.sh does)

```bash
# 1. Universal Auth login → access token
curl -fsS -X POST "${INFISICAL_API_URL}/api/v1/auth/universal-auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"clientId":"…","clientSecret":"…"}'

# 2. Fetch all raw secrets for the project+environment
curl -sS "${INFISICAL_API_URL}/api/v3/secrets/raw?workspaceId=${INFISICAL_PROJECT_ID}&environment=${INFISICAL_ENVIRONMENT}" \
  -H "Authorization: Bearer ${TOKEN}"

# 3. Export every key/value into the process env (shell-quoted), then:
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8090}"
```

Deploy and verify:

```bash
docker compose up -d --build
docker logs pii-masking 2>&1 | grep '\[entrypoint\]'
# expect: "Authenticating to Infisical..." → "Secrets loaded from Infisical (<id>)"
curl -s http://localhost:8090/health
```

## Rotation

```bash
# 1. Update the secret value in Infisical (UI, CLI, or API)
# 2. Restart the container — the entrypoint re-fetches at boot
docker compose restart pii-masking
# 3. For PII_HASH_SALT: restarting with a NEW salt invalidates token
#    consistency with previously issued masked text — rotate deliberately.
```

## Fallback behavior

- Missing `INFISICAL_CLIENT_ID`/`INFISICAL_CLIENT_SECRET` → entrypoint skips
  Infisical and runs with plain env vars.
- `PII_MASTER_KEY` absent → auto-generated 32-hex key, logged once (capture
  via `docker logs pii-masking`).
- `PII_HASH_SALT` absent → ephemeral salt with a loud warning; tokens are
  not stable across restarts.
