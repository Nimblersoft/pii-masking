# Reversible masking via salted hash tokens

We mask PII by replacing each detected value with a placeholder token of the
form `[TYPE_xxxxxxxx]`, where the suffix is the first 8 hex chars of a salted
SHA-256 of the original value. The same value always maps to the same token, and
restoration is delegated to the caller, which swaps tokens back using the
`entities` mapping returned by `/mask`.

## Considered options

- **Static type-only placeholders** (`[PERSON]`) — the original implementation.
  Rejected: two different people both become `[PERSON]`, so the caller cannot
  restore the text. Round-trip is impossible.
- **Indexed placeholders** (`[PERSON_1]`, `[PERSON_2]`) — unique per occurrence.
  Rejected: indices are request-local, so the same value gets different tokens
  across requests; no cross-request consistency, and it requires stateful
  counters in the anonymizer.
- **Presidio `encrypt` operator** — reversible server-side. Rejected: requires
  the service to hold/manage an encryption key and makes the service stateful
  for restoration. We deliberately keep PII↔token mapping out of the service.
- **Salted hash tokens (chosen)** — consistent within and across requests given
  a stable salt, no server-side PII state, restoration owned by the caller.

## Consequences

- Cross-request consistency requires a **stable `PII_HASH_SALT`** (sourced from
  Infisical/env). If unset, an ephemeral salt is generated and consistency is
  lost across restarts — logged as a warning.
- A deterministic hash of low-entropy values (common names, emails) is
  brute-forceable; the salt is what protects tokens exposed in masked text sent
  to the LLM. The salt is therefore a secret, not just a config value.
- Restoration depends on the caller retaining the returned `entities`; the hash
  is one-way and cannot be inverted by the service.
