"""User redaction files: extra rules that run alongside a pack's own rules."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from dutygate import Gate, PackError, load_policy
from dutygate.cli import main

from .helpers import THREE_RULES, StaticBackend

ACCOUNT_RULES = """\
redaction:
  - name: account_number
    pattern: 'ACC-\\d{6,10}'
    replacement: '[ACCOUNT]'
  - name: member_id
    pattern: 'NW\\d{8}'
"""


def zeros() -> dict[str, float]:
    return {q["id"]: 0.0 for q in THREE_RULES["questions"]}


@pytest.fixture
def rules_file(tmp_path: Path) -> Path:
    path = tmp_path / "redaction.yaml"
    path.write_text(ACCOUNT_RULES)
    return path


def names(pack_rules: tuple) -> list[str]:  # type: ignore[type-arg]
    return [r.name for r in pack_rules]


def test_user_rules_run_before_the_pack_rules(rules_file: Path) -> None:
    pack = load_policy("legal-triggers", redaction=rules_file)
    assert names(pack.redaction)[:2] == ["account_number", "member_id"]
    assert names(pack.redaction)[2:] == names(load_policy("legal-triggers").redaction)


def test_gate_redacts_with_user_and_pack_rules(rules_file: Path) -> None:
    backend = StaticBackend(zeros())
    gate = Gate.from_pack(THREE_RULES, backend, redaction=rules_file)  # type: ignore[arg-type]
    gate.check("account ACC-1234567 member NW12345678, mail x@y.com")
    assert backend.requests[0].state == {
        "customer_message": "account [ACCOUNT] member [MEMBER_ID], mail [EMAIL]"
    }


def test_env_var_applies_when_no_file_is_passed(
    rules_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DUTYGATE_REDACTION_FILE", str(rules_file))
    assert names(load_policy("outbound-claims").redaction)[0] == "account_number"


def test_explicit_file_beats_env_var(
    rules_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = tmp_path / "other.yaml"
    other.write_text("redaction:\n  - name: ticket\n    pattern: 'T-\\d+'\n")
    monkeypatch.setenv("DUTYGATE_REDACTION_FILE", str(other))
    assert names(load_policy(THREE_RULES, redaction=rules_file).redaction)[0] == "account_number"


def test_empty_env_var_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DUTYGATE_REDACTION_FILE", "")
    assert names(load_policy(THREE_RULES).redaction) == ["email"]


def test_missing_file_fails_instead_of_skipping(tmp_path: Path) -> None:
    with pytest.raises(PackError, match="redaction file not found"):
        load_policy(THREE_RULES, redaction=tmp_path / "nope.yaml")


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("redaction:\n  - name: bad\n    pattern: '(unclosed'\n", "redaction.bad: invalid regex"),
        ("rules: []\n", "rules: Extra inputs are not permitted"),
        ("- name: x\n  pattern: y\n", "must be a YAML mapping"),
        ("redaction: [\n", "invalid YAML"),
        ("redaction:\n  - name: email\n    pattern: 'x'\n", "duplicate redaction name 'email'"),
        ("redaction:\n  - name: Bad Name\n    pattern: 'x'\n", "redaction.0.name"),
    ],
    ids=["bad-regex", "unknown-key", "not-a-mapping", "bad-yaml", "clashes-with-pack", "bad-name"],
)
def test_invalid_file_is_reported_with_its_path(tmp_path: Path, content: str, message: str) -> None:
    path = tmp_path / "mine.yaml"
    path.write_text(content)
    with pytest.raises(PackError) as exc:
        load_policy(THREE_RULES, redaction=path)
    assert message in str(exc.value)
    assert str(path) in str(exc.value)


def test_cli_validate_includes_the_env_file(
    rules_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DUTYGATE_REDACTION_FILE", str(rules_file))
    res = CliRunner().invoke(main, ["validate", "legal-triggers"])
    assert res.exit_code == 0, res.output
    assert "2 extra redaction rules" in res.output


def test_cli_validate_fails_on_a_bad_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("redaction:\n  - name: bad\n    pattern: '(unclosed'\n")
    monkeypatch.setenv("DUTYGATE_REDACTION_FILE", str(bad))
    res = CliRunner().invoke(main, ["validate", "legal-triggers"])
    assert res.exit_code == 1
    assert "invalid regex" in res.output
