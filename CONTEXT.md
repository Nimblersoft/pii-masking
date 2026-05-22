# PII Masking

The shared language of a service that detects personal data in free-form text
and substitutes it with placeholder tokens, so the text can be sent to an LLM
(or other third party) and the original data restored afterwards.

## Language

**Mask**:
To substitute each detected PII span in a text with a typed placeholder token.
The canonical name for the core operation this service performs.
_Avoid_: anonymize (Presidio's internal term, implies irreversibility), redact
(implies removal/blacking-out rather than substitution).

**PII Entity**:
A span of text identified as personal data — a person, organization, email,
phone number, or credit card. Carries an original value, a type label, and its
character offsets in the source text.
_Avoid_: match, detection (use for the act, not the thing).

**Placeholder Token**:
The string that replaces a PII Entity in masked text, of the form
`[TYPE_xxxxxxxx]` where the suffix is a salted, truncated, one-way hash of the
original value. The same value always yields the same token (given a stable
salt), which is what makes restoration possible.
_Avoid_: placeholder, mask token, tag. Note: distinct from **API Token** — see
the flagged ambiguity below.

**Restoration**:
The caller-side act of turning masked text back into the original by replacing
each Placeholder Token with its PII Entity's original value, using the mapping
returned in the response. Performed by the caller, not the service; the hash
itself is not invertible.
_Avoid_: unmask, decrypt, reverse.

**Master Key**:
The single secret that authorizes the token-administration surface
(`/tokens`). Not used for masking.
_Avoid_: admin key, root key.

**API Token**:
A per-client credential (`pii_<hex>`) presented as `X-API-Key` to authorize
`/mask` when key enforcement is on. Stored only as a hash; the raw value is
shown once at creation.
_Avoid_: API key (acceptable as the header name only), client token.

## Flagged ambiguities

**"Token" is overloaded.** Two unrelated concepts share the word:
- **Placeholder Token** — replaces PII inside text (`[PERSON_3a7f1c08]`).
- **API Token** — authenticates a client (`pii_<hex>`).
Always qualify which one you mean. They never interact.

## Example dialogue

> **Dev:** When we mask a message, do we strip the names out?
> **Domain expert:** No — we *mask* them: each name becomes a Placeholder
> Token, not a hole. `[PERSON_3a7f1c08]`.
> **Dev:** And if "Acme" shows up three times?
> **Domain expert:** Same token all three times — the token is a salted hash of
> the value, so equal values collapse. That consistency is the whole point: the
> LLM sees one stable reference, and on the way back we do Restoration by
> swapping each token for its original value from the entities list.
> **Dev:** Could we just reverse the hash instead of carrying the mapping?
> **Domain expert:** No, the hash is one-way. Restoration always uses the
> returned PII Entities. If the caller doesn't need to restore, it asks us not
> to return them at all.
> **Dev:** And the API Token gates this call?
> **Domain expert:** Only when key enforcement is on — and don't confuse it with
> the Placeholder Tokens in the text. Different things, same unfortunate word.
