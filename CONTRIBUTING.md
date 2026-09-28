# Contributing to DutyGate

Thanks for helping. Bug reports, pack improvements, new language examples and labeled
evaluation data are all welcome.

## Setup

```console
git clone https://github.com/Taimoor2500/Dutygate && cd Dutygate
uv sync --extra server --extra langchain     # Python 3.10+
uv run pytest                                # no network needed
cd clients/typescript && npm ci && npm test
```

## Before opening a pull request

```console
uv run ruff check && uv run ruff format --check && uv run mypy
uv run pytest --cov=dutygate --cov-fail-under=90
cd clients/typescript && npm run typecheck && npm test && npm run test:e2e
```

- **Tests first.** New behavior needs a test that fails without your change.
- **Contract changes** go in `SPEC.md` and `conformance/cases.json` in the same pull request.
  Every surface (engine, sidecar, TypeScript client) must pass the conformance suite.
- **Pack changes** (question wording, thresholds, new categories) need:
  - a bump of the pack's `version`
  - an eval run showing the effect: `dutygate eval ...` before and after, pasted in the PR
- **New dataset rows** must be synthetic or properly anonymized and consented. Never commit
  real customer messages.
- **Tests stay offline.** Tests that call TypeSafe carry the `live` marker and are skipped
  without `TYPESAFE_API_KEY`.

## Project layout

| path | |
|---|---|
| `src/dutygate/` | library, CLI, sidecar (`server/`), adapters |
| `packs/` | reference policy packs |
| `conformance/` | cross-surface contract cases |
| `evals/` | datasets and keyword baselines |
| `clients/typescript/` | npm client |
| `examples/` | runnable integrations |
| `docs/` | integration, sidecar, adapter, privacy and labeling guides |

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).
