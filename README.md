# pii-masking

FastAPI microservice that masks PII (names, organizations, emails, phone
numbers, credit cards) in text using Microsoft Presidio + spaCy. English
and Spanish supported.

See [AGENTS.md](./AGENTS.md) for full architecture, API contract, auth
model, and integration notes.

## Quick start

```bash
docker compose up -d --build
curl -s http://localhost:8090/health

curl -s -X POST http://localhost:8090/mask \
  -H 'Content-Type: application/json' \
  -d '{"text":"Hi I am John Smith from Acme Inc, email john@acme.com","language":"en"}'
```

PII is replaced with stable, salted placeholder tokens like `[PERSON_3a7f1c08]`.
The response's `entities` list maps each token back to its original value, so a
caller can mask text before sending it to an LLM and restore the PII afterwards.
Pass `"return_entities": false` to get only the masked text. Set a stable
`PII_HASH_SALT` so tokens stay consistent across restarts.

## Token management

The `./cli` wrapper automatically resolves `PII_MASTER_KEY` from the running
container, so you can invoke commands directly:

```bash
./cli generate   # Create a new API token
./cli list       # List active tokens
./cli revoke <token-id>  # Revoke a token
```

The wrapper reads `PII_MASTER_KEY` from the running container (or your shell
environment if set). You can override it:

```bash
./cli --master-key <key> list
PII_CONTAINER=my-service ./cli list  # Use a different container name
```

Set `REQUIRE_API_KEY=true` in your environment to enforce `X-API-Key` on
`/mask`. Default is open — suitable for internal-only deployments.

## Configuration

Copy [.env.example](./.env.example) to `.env` and fill in values. `.env` is
gitignored — never commit real secrets.

## Tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

## License

MIT — see [LICENSE](./LICENSE).
