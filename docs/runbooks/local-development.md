---
title: "Runbook: Local Development"
type: runbook
status: active
confidence: strong
tags:
  - runbook
  - development
last_checked: 2026-09-03
---

# Local Development

Copy-paste setup for hacking on the service locally (Python 3.11).

```bash
# 0. Clone and enter
git clone <repo-url> pii-masking && cd pii-masking

# 1. Create + activate venv (rebuild from scratch if it was ever moved —
#    relocated venvs keep broken shebangs in bin/)
python3.11 -m venv .venv
source .venv/bin/activate

# 2. Install pinned runtime + dev dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-dev.txt

# 3. Download the spaCy models the engine loads (must match Dockerfile)
python -m spacy download en_core_web_sm
python -m spacy download es_core_news_sm

# 4. Verify the environment is coherent
pip check

# 5. Run the test suite (warm-starts the engine; ~3s after models load)
pytest -v tests/
#    E2E subset only (boots a real uvicorn server on an ephemeral port):
pytest -m e2e
#    Everything except E2E:
pytest -m 'not e2e'

# 6. Run the server locally (optional)
export PII_HASH_SALT=dev-salt            # stable tokens across restarts
export PII_MASTER_KEY=dev-master-key
uvicorn app.main:app --host 0.0.0.0 --port 8090

# 7. Smoke-test
curl -s http://localhost:8090/health
curl -s -X POST http://localhost:8090/mask \
  -H 'Content-Type: application/json' \
  -d '{"text":"Hi I am John Smith, email john@acme.com","language":"en"}'
```

Notes:

- Tests are deterministic: `tests/conftest.py` pins `PII_HASH_SALT`,
  `PII_MASTER_KEY`, and `REQUIRE_API_KEY=false` before the app imports.
- Model accuracy upgrade path: swap `en_core_web_sm`/`es_core_news_sm` for
  the `_md` builds — must be done **together** in `Dockerfile` and the
  `NlpEngineProvider` config in `app/pii_engine.py`, then re-run the suite.
- Dependency changes: keep the spaCy-coupled pins
  (`spacy`/`thinc`/`blis`/`confection`/`numpy`) moving as one unit — see the
  comments in `requirements.txt`.
