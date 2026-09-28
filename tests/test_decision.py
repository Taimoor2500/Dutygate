import json
import re

from dutygate.decision import Decision, ErrorInfo, Flag, new_decision_id
from dutygate.errors import BackendError, PackError

SPEC_EXAMPLE = {
    "id": "dec_4f1c2a9e8b7d4c3fa1e2b3c4d5e6f708",
    "action": "route",
    "primary": "privacy_request",
    "flags": [
        {
            "category": "privacy_request",
            "rule_id": "privacy-request",
            "queue": "privacy",
            "priority": "high",
            "confidence": 0.93,
            "level": "confident",
        },
        {
            "category": "opt_out",
            "rule_id": "opt-out",
            "queue": "compliance",
            "priority": "high",
            "confidence": 0.31,
            "level": "grey",
        },
    ],
    "error": None,
    "policy": {"name": "legal-triggers", "version": "0.1.0"},
    "backend": {"name": "typesafe-jev", "model": "jev-1.13.0"},
    "conversation_id": "c_123",
    "latency_ms": 212,
}


def _example() -> Decision:
    return Decision(
        id="dec_4f1c2a9e8b7d4c3fa1e2b3c4d5e6f708",
        action="route",
        primary="privacy_request",
        flags=(
            Flag("privacy_request", "privacy-request", "privacy", "high", 0.93, "confident"),
            Flag("opt_out", "opt-out", "compliance", "high", 0.31, "grey"),
        ),
        error=None,
        policy={"name": "legal-triggers", "version": "0.1.0"},
        backend={"name": "typesafe-jev", "model": "jev-1.13.0"},
        conversation_id="c_123",
        latency_ms=212,
    )


def test_to_dict_matches_spec_example_exactly() -> None:
    d = _example().to_dict()
    assert d == SPEC_EXAMPLE
    assert list(d.keys()) == list(SPEC_EXAMPLE.keys())
    assert list(d["flags"][0].keys()) == list(SPEC_EXAMPLE["flags"][0].keys())  # type: ignore[index]


def test_round_trip() -> None:
    dec = _example()
    assert Decision.from_dict(dec.to_dict()) == dec


def test_round_trip_with_error() -> None:
    dec = Decision.from_dict(
        {
            **SPEC_EXAMPLE,
            "flags": [],
            "action": "review",
            "primary": None,
            "error": {"code": "backend_timeout", "message": "slow"},
        }
    )
    assert dec.error == ErrorInfo("backend_timeout", "slow")
    assert dec.to_dict()["error"] == {"code": "backend_timeout", "message": "slow"}


def test_to_json_keeps_non_ascii() -> None:
    dec = Decision.from_dict({**SPEC_EXAMPLE, "conversation_id": "محادثة"})
    out = dec.to_json()
    assert "محادثة" in out
    assert json.loads(out)["conversation_id"] == "محادثة"


def test_new_decision_id_format() -> None:
    assert re.fullmatch(r"dec_[0-9a-f]{32}", new_decision_id())
    assert new_decision_id() != new_decision_id()


def test_backend_error_carries_code() -> None:
    err = BackendError("backend_timeout", "x")
    assert err.code == "backend_timeout"
    assert err.message == "x"


def test_pack_error_lists_all_errors() -> None:
    err = PackError(["a", "b"])
    assert err.errors == ["a", "b"]
    assert "a" in str(err) and "b" in str(err)
