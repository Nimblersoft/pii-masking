# Changelog

Preserve published release entries here, grouped by actual version and release date.
Do not invent prior releases or dates.

## [Unreleased]

### Added

- Add custom Ecuadorian and financial PII recognizers in `app/recognizers.py`: `EC_CEDULA` (`CEDULA`), `EC_RUC` (`RUC`), contextual `BANK_ACCOUNT` (`ACCOUNT`), and contextual `SECRET_CREDENTIAL` (`SECRET`), plus Ecuadorian (`EC`) phone region and Spanish phone context support.
- Add backward-compatible optional `entities` (supporting canonical Presidio names and output labels, HTTP 400 on unknown values) and bounded case-insensitive `allow_list` (overlap-excluding, max 100 items / 120 chars each) parameters to `POST /mask` and `PIIEngine.mask()`.
- Add unit and API regression tests in `tests/test_ec_recognizers.py`.

### Changed

- Eliminate Spanish banking/greeting NER false positives by unmapping `MISC` from `ORGANIZATION`, filtering generic Spanish banking/greeting false detections, and rescuing Spanish compound names (e.g. `"María José López"`).
- Resolve cross-entity overlapping spans deterministically before anonymization so `masked` text and returned `entities` always match 1-to-1.
- Establish release-history ownership in `CHANGELOG.md`, current-state documentation, and pre-release/post-release ADR rules.
