#!/bin/bash
set -euo pipefail

INFISICAL_API_URL="${INFISICAL_API_URL:-https://app.infisical.com}"
INFISICAL_PROJECT_ID="${INFISICAL_PROJECT_ID:-}"
INFISICAL_ENVIRONMENT="${INFISICAL_ENVIRONMENT:-dev}"

# Fallback: no Infisical → run uvicorn directly
if [[ -z "${INFISICAL_CLIENT_ID:-}" || -z "${INFISICAL_CLIENT_SECRET:-}" ]]; then
  echo "[entrypoint] No Infisical credentials — running with env vars only"
  exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8090}"
fi

# Step 1: Get access token
echo "[entrypoint] Authenticating to Infisical..."
RESPONSE=$(curl -fsS -X POST "${INFISICAL_API_URL}/api/v1/auth/universal-auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"clientId\": \"${INFISICAL_CLIENT_ID}\", \"clientSecret\": \"${INFISICAL_CLIENT_SECRET}\"}")

TOKEN=$(printf '%s' "$RESPONSE" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("accessToken",""))')

if [[ -z "$TOKEN" ]]; then
  echo "[entrypoint] ERROR: Failed to get Infisical access token" >&2
  exit 1
fi

# Step 2: Fetch all secrets from PII Masking project
echo "[entrypoint] Fetching secrets from Infisical project ${INFISICAL_PROJECT_ID} (env: ${INFISICAL_ENVIRONMENT})..."
SECRETS_RESPONSE=$(curl -sS --connect-timeout 10 \
  "${INFISICAL_API_URL}/api/v3/secrets/raw?workspaceId=${INFISICAL_PROJECT_ID}&environment=${INFISICAL_ENVIRONMENT}" \
  -H "Authorization: Bearer ${TOKEN}")

if [[ -z "$SECRETS_RESPONSE" ]]; then
  echo "[entrypoint] ERROR: Failed to fetch secrets from Infisical" >&2
  exit 1
fi

# Step 3: Export each secret as env var
EXPORTS=$(printf '%s' "$SECRETS_RESPONSE" | python3 -c '
import json, shlex, sys
data = json.load(sys.stdin)
for s in data.get("secrets", []):
    key = s.get("secretKey", "")
    val = s.get("secretValue", "")
    if key and val:
        print("export {}={}".format(key, shlex.quote(val)))
')

eval "$EXPORTS"
echo "[entrypoint] Secrets loaded from Infisical (${INFISICAL_PROJECT_ID})"

# Step 4: Start uvicorn
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8090}"
