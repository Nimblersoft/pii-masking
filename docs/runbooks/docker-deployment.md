---
title: "Runbook: Docker Deployment"
type: runbook
status: active
confidence: strong
tags:
  - runbook
  - deployment
  - docker
last_checked: 2026-09-03
---

# Docker Deployment

Single-container deployment via Docker Compose. The first build downloads
and installs the spaCy models (~50 MB extra) — expect a few minutes.

```bash
# 1. Build (validates the image against pinned requirements)
docker compose build

# 2. Start (daemonized). Secrets come from the host env or Infisical —
#    see the Infisical runbook for the full path.
docker compose up -d

# 3. Wait for health, then probe
curl -s http://localhost:8090/health
# → {"status":"ok","models":["en","es"]}

# 4. Smoke-test masking
curl -s -X POST http://localhost:8090/mask \
  -H 'Content-Type: application/json' \
  -d '{"text":"Contact John Smith at john@acme.com","language":"en","return_entities":true}'

# 5. Manage API tokens (wrapper resolves PII_MASTER_KEY from the container)
./cli generate
./cli list
./cli revoke <token-id>

# 6. Logs / teardown
docker logs pii-masking
docker compose down
```

Health checks:

- Compose healthcheck: `curl -f http://localhost:8090/health` every 10s,
  15s start period, 5 retries; container reports `healthy` once the engine
  is warm.
- The image's own `HEALTHCHECK` (30s interval, 30s start period) covers
  non-compose `docker run` usage.

Hardening already baked in: non-root `appuser` (uid 1001),
`no-new-privileges:true`, internal networks only (the compose file also
joins the external `infisical_infisical` network for secret fetch), and no
secrets baked into the image.

Common issues:

| Symptom | Fix |
|---|---|
| Restart regenerated all API tokens | Expected — token store is in-memory. Re-seed via `PII_API_TOKEN` or `./cli generate` |
| Tokens differ across restarts | `PII_HASH_SALT` not provided — set it (Infisical or env) |
| Master key unknown | `docker logs pii-masking` — an auto-generated key is logged once |
| First requests slow | Engine warm-starts in lifespan; wait for `/health` before serving traffic |
