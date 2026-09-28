## What and why

## Checklist

- [ ] Tests added first (they fail without this change)
- [ ] `uv run ruff check && uv run ruff format --check && uv run mypy && uv run pytest` pass
- [ ] Contract changes are reflected in `SPEC.md` and `conformance/cases.json`
- [ ] Pack changes bump the pack `version` and include before/after `dutygate eval` output
- [ ] No real customer data anywhere in this PR
- [ ] `CHANGELOG.md` updated under "Unreleased"
