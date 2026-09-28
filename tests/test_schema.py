import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from dutygate.errors import PackError
from dutygate.schema import Thresholds, load_policy, load_policy_with_warnings

MINIMAL: dict[str, Any] = {
    "schema_version": 1,
    "name": "mini",
    "version": "0.1.0",
    "questions": [
        {"id": "q_threat", "instructions": "Does the customer threaten legal action?"},
        {"id": "q_optout", "instructions": "Does the customer ask to stop messages?"},
    ],
    "rules": [
        {
            "id": "threat",
            "category": "legal_threat",
            "questions": ["q_threat"],
            "queue": "legal",
            "priority": "urgent",
        },
        {
            "id": "opt-out",
            "category": "opt_out",
            "questions": ["q_optout"],
            "queue": "compliance",
            "priority": "high",
            "thresholds": {"low": 0.1, "high": 0.3},
        },
    ],
}


def pack_with(**changes: Any) -> dict[str, Any]:
    data = copy.deepcopy(MINIMAL)
    data.update(changes)
    return data


def errors_for(data: dict[str, Any]) -> str:
    with pytest.raises(PackError) as exc:
        load_policy(data)
    return "\n".join(exc.value.errors)


def warnings_for(data: dict[str, Any]) -> str:
    _, warnings = load_policy_with_warnings(data)
    return "\n".join(warnings)


# ---------- positive ----------


def test_minimal_pack_loads_with_defaults() -> None:
    pack = load_policy(MINIMAL)
    assert pack.name == "mini"
    assert pack.state_field == "customer_message"
    assert pack.defaults.thresholds == Thresholds(low=0.2, high=0.5)
    assert pack.defaults.on_error == "review"
    assert pack.limits.max_message_chars == 8000
    assert pack.context.max_recent_messages == 0
    assert pack.rules[0].match == "any"


def test_thresholds_for_uses_override_then_defaults() -> None:
    pack = load_policy(MINIMAL)
    assert pack.thresholds_for(pack.rules[0]) == Thresholds(low=0.2, high=0.5)
    assert pack.thresholds_for(pack.rules[1]) == Thresholds(low=0.1, high=0.3)


def test_question_lookup() -> None:
    pack = load_policy(MINIMAL)
    assert pack.question("q_optout").instructions.startswith("Does the customer ask")


def test_questions_digest_stable_and_sensitive() -> None:
    a = load_policy(MINIMAL).questions_digest
    reordered = pack_with(questions=list(reversed(MINIMAL["questions"])))
    assert load_policy(reordered).questions_digest == a
    reworded = copy.deepcopy(MINIMAL)
    reworded["questions"][0]["instructions"] = "Is the customer threatening to sue?"
    assert load_policy(reworded).questions_digest != a
    with_criteria = copy.deepcopy(MINIMAL)
    with_criteria["questions"][0]["criteria"] = {"true": "yes", "false": "no"}
    assert load_policy(with_criteria).questions_digest != a
    assert len(a) == 64


def test_load_from_path_and_str(tmp_path: Path) -> None:
    p = tmp_path / "pack.yaml"
    p.write_text(yaml.safe_dump(MINIMAL), encoding="utf-8")
    assert load_policy(p).name == "mini"
    assert load_policy(str(p)).name == "mini"


def test_yaml_criteria_true_false_keys(tmp_path: Path) -> None:
    # YAML 1.1 parses bare `true:` / `false:` keys as booleans; the pack must still load.
    p = tmp_path / "pack.yaml"
    text = yaml.safe_dump(MINIMAL).replace(
        "- id: q_threat\n",
        "- id: q_threat\n  criteria:\n    true: mentions a lawyer\n    false: no legal threat\n",
    )
    p.write_text(text, encoding="utf-8")
    crit = load_policy(p).question("q_threat").criteria
    assert crit is not None
    assert (crit.true, crit.false) == ("mentions a lawyer", "no legal threat")


def test_reserved_state_field_rejected() -> None:
    assert "state_field" in errors_for(pack_with(state_field="channel"))


def test_rule_lists_question_twice() -> None:
    rules = copy.deepcopy(MINIMAL["rules"])
    rules[0]["questions"] = ["q_threat", "q_threat"]
    assert "twice" in errors_for(pack_with(rules=rules))


def test_missing_file_is_pack_error(tmp_path: Path) -> None:
    with pytest.raises(PackError, match="not found"):
        load_policy(tmp_path / "nope.yaml")


def test_invalid_yaml_is_pack_error(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("rules: [unclosed", encoding="utf-8")
    with pytest.raises(PackError, match="YAML"):
        load_policy(p)


def test_non_mapping_yaml_is_pack_error(tmp_path: Path) -> None:
    p = tmp_path / "list.yaml"
    p.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(PackError, match="mapping"):
        load_policy(p)


def test_clean_pack_has_no_warnings() -> None:
    assert warnings_for(MINIMAL) == ""


# ---------- errors ----------


def test_unknown_key() -> None:
    assert "surprise" in errors_for(pack_with(surprise=1))


def test_unsupported_schema_version() -> None:
    assert "schema_version" in errors_for(pack_with(schema_version=2))


def test_duplicate_question_id() -> None:
    qs = MINIMAL["questions"] + [{"id": "q_threat", "instructions": "again"}]
    assert "duplicate question id 'q_threat'" in errors_for(pack_with(questions=qs))


def test_duplicate_rule_id() -> None:
    rules = MINIMAL["rules"] + [dict(MINIMAL["rules"][0])]
    assert "duplicate rule id 'threat'" in errors_for(pack_with(rules=rules))


def test_duplicate_redaction_name() -> None:
    red = [{"name": "email", "pattern": "a"}, {"name": "email", "pattern": "b"}]
    assert "duplicate redaction name 'email'" in errors_for(pack_with(redaction=red))


def test_rule_references_unknown_question() -> None:
    rules = copy.deepcopy(MINIMAL["rules"])
    rules[0]["questions"] = ["q_missing"]
    assert "unknown question 'q_missing'" in errors_for(pack_with(rules=rules))


def test_rule_with_no_questions() -> None:
    rules = copy.deepcopy(MINIMAL["rules"])
    rules[0]["questions"] = []
    assert "questions" in errors_for(pack_with(rules=rules))


def test_low_above_high() -> None:
    d = pack_with(defaults={"thresholds": {"low": 0.6, "high": 0.5}})
    assert "low" in errors_for(d)


def test_high_above_one() -> None:
    rules = copy.deepcopy(MINIMAL["rules"])
    rules[0]["thresholds"] = {"low": 0.2, "high": 1.5}
    assert "high" in errors_for(pack_with(rules=rules))


def test_bad_regex() -> None:
    red = [{"name": "broken", "pattern": "([a-z"}]
    assert "broken" in errors_for(pack_with(redaction=red))


def test_non_semver_version() -> None:
    assert "version" in errors_for(pack_with(version="1.0"))


def test_zero_rules() -> None:
    assert "rules" in errors_for(pack_with(rules=[]))


def test_bad_question_id_format() -> None:
    qs = copy.deepcopy(MINIMAL["questions"])
    qs[0]["id"] = "Legal-Threat"
    assert "Legal-Threat" in errors_for(pack_with(questions=qs))


def test_bad_rule_id_format() -> None:
    rules = copy.deepcopy(MINIMAL["rules"])
    rules[0]["id"] = "legal threat"
    assert "legal threat" in errors_for(pack_with(rules=rules))


def test_all_errors_reported_together() -> None:
    rules = copy.deepcopy(MINIMAL["rules"])
    rules[0]["questions"] = ["q_missing"]
    red = [{"name": "broken", "pattern": "([a-z"}]
    text = errors_for(pack_with(rules=rules, redaction=red))
    assert "q_missing" in text and "broken" in text


# ---------- warnings ----------


def test_warn_unused_question() -> None:
    qs = MINIMAL["questions"] + [{"id": "q_unused", "instructions": "?"}]
    assert "q_unused" in warnings_for(pack_with(questions=qs))


def test_warn_on_error_continue() -> None:
    assert "fails open" in warnings_for(pack_with(defaults={"on_error": "continue"}))


def test_warn_priority_out_of_order() -> None:
    rules = copy.deepcopy(MINIMAL["rules"])
    rules[0]["priority"] = "low"
    assert "priority" in warnings_for(pack_with(rules=rules))


def test_warn_no_grey_zone() -> None:
    rules = copy.deepcopy(MINIMAL["rules"])
    rules[1]["thresholds"] = {"low": 0.4, "high": 0.4}
    assert "grey zone" in warnings_for(pack_with(rules=rules))


def test_warn_pattern_matches_empty() -> None:
    red = [{"name": "greedy", "pattern": "a*"}]
    assert "greedy" in warnings_for(pack_with(redaction=red))


def test_bundled_packs_load_by_name() -> None:
    from dutygate import bundled_packs

    assert bundled_packs() == ["legal-triggers", "outbound-claims"]
    assert load_policy("legal-triggers").name == "legal-triggers"
    assert load_policy("outbound-claims").state_field == "assistant_reply"


def test_unknown_name_lists_bundled_packs() -> None:
    with pytest.raises(PackError, match="legal-triggers"):
        load_policy("no-such-pack")


def test_file_path_wins_over_bundled_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "legal-triggers").write_text(yaml.safe_dump(MINIMAL), encoding="utf-8")
    assert load_policy("legal-triggers").name == "mini"
