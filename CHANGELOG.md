# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Redaction files: your own redaction rules, in a YAML file named by `DUTYGATE_REDACTION_FILE`
  or `Gate.from_pack(..., redaction=...)`. They run before the pack's rules, and both apply.
  A missing or invalid file is an error, never skipped. `load_redaction()` loads one directly.

### Changed
- Packs `legal-triggers` 0.2.0 and `outbound-claims` 0.2.0 also redact phone numbers, IBANs and
  national IDs (US SSN, UK National Insurance number, Pakistani CNIC, Emirates ID) before any
  backend call.

## [0.1.0] - 2026-09-28

### Added
- Policy pack format (`schema_version: 1`) with validation that reports every error at once,
  plus warnings.
- Engine with one backend call per message; `match: any|all`; per-rule thresholds; confident
  and grey flags; fail-safe error decisions with machine-readable codes.
- Backends:
  - TypeSafe Jev: total time budget, retries on 429/529/5xx
  - replay: fixtures bound to a questions digest
  - keyword: evaluation baseline only
- Redaction before any backend call: emails, and card numbers only when they pass a Luhn check.
- `Gate` facade (sync and async).
- CLI: `validate`, `run`, `eval` and `serve`.
- Evaluation harness: metrics per category and per tag, `--save-answers`, `--replay`,
  threshold `--sweep`, keyword baseline comparison, and `--fail-under` gates for CI.
- HTTP sidecar:
  - bearer auth with key rotation, multi-pack routing, a body size limit
  - Prometheus metrics and an opt-in audit log
  - JSON logs without message text
  - Docker image
- TypeScript client `dutygate-client`: zero dependencies, fail-safe `review` fallback,
  ESM and CJS builds.
- `GatedHandler` for any web framework, the LangChain `with_legal_gate` adapter, and LangGraph
  `gate_node` / `outbound_node` (extra `langgraph`).
- Packs: `legal-triggers` (inbound) and `outbound-claims` (the bot's replies), bundled in the
  package with their sample datasets and keyword baselines, and loadable by name.
- `dutygate init <pack>` copies a bundled pack, its dataset and its keywords into your project
  to customize. `dutygate eval <pack>` and `--backend keyword` default to the bundled files.
- Conformance suite (55 cases), run through the engine, the sidecar and the TypeScript client.
- Synthetic evaluation datasets (159 and 66 rows) with keyword baselines.

### Known limitations
- The TypeSafe Jev integration follows the published API reference but has not yet been
  verified against the live API.
- Question wording and thresholds are untuned.
