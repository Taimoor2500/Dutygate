import asyncio
from pathlib import Path
from typing import Any

import pytest
import yaml

import dutygate
from dutygate import Decision, Gate, ReplayBackend, default_holding_reply, evaluate
from dutygate.holding import DEFAULT_HOLDING_REPLY

from .helpers import THREE_RULES, StaticBackend, make_pack, zeros


class ClosingBackend(StaticBackend):
    def __init__(self) -> None:
        super().__init__(zeros())
        self.closed = 0
        self.aclosed = 0

    def close(self) -> None:
        self.closed += 1

    async def aclose(self) -> None:
        self.aclosed += 1


def test_check_equals_evaluate() -> None:
    pack = make_pack()
    scores = zeros(q_a=0.9)
    g = Gate(pack, StaticBackend(scores)).check("hi", conversation_id="c", channel="web")
    e = evaluate(pack, "hi", StaticBackend(scores), conversation_id="c", channel="web")
    assert (g.action, g.primary, g.flags, g.conversation_id) == (
        e.action,
        e.primary,
        e.flags,
        e.conversation_id,
    )


def test_on_decision_called_once() -> None:
    seen: list[Decision] = []
    gate = Gate(make_pack(), StaticBackend(zeros()), on_decision=seen.append)
    d = gate.check("hi")
    assert seen == [d]


def test_on_decision_exception_swallowed(caplog: pytest.LogCaptureFixture) -> None:
    def boom(_: Decision) -> None:
        raise RuntimeError("audit sink down")

    d = Gate(make_pack(), StaticBackend(zeros()), on_decision=boom).check("hi")
    assert d.action == "continue"
    assert "on_decision" in caplog.text


async def test_async_on_decision() -> None:
    seen: list[Decision] = []
    gate = Gate(make_pack(), StaticBackend(zeros(q_a=0.3)), on_decision=seen.append)
    d = await gate.check_async("hi")
    assert d.action == "review" and seen == [d]


def test_context_manager_closes_backend() -> None:
    backend = ClosingBackend()
    with Gate(make_pack(), backend) as gate:
        gate.check("hi")
    assert backend.closed == 1


async def test_async_context_manager_closes_backend() -> None:
    backend = ClosingBackend()
    async with Gate(make_pack(), backend) as gate:
        await gate.check_async("hi")
    assert backend.aclosed == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"message": None},
        {"message": 123},
        {"message": "ok", "recent_messages": ["ok", 3]},
        {"message": "ok", "recent_messages": "notalist"},
        {"message": "ok", "channel": 5},
        {"message": "ok", "conversation_id": 7},
    ],
)
def test_wrong_argument_types_raise_type_error(kwargs: dict[str, Any]) -> None:
    gate = Gate(make_pack(), StaticBackend(zeros()))
    message = kwargs.pop("message")
    with pytest.raises(TypeError):
        gate.check(message, **kwargs)


async def test_wrong_argument_types_raise_type_error_async() -> None:
    with pytest.raises(TypeError):
        await Gate(make_pack(), StaticBackend(zeros())).check_async(None)  # type: ignore[arg-type]


async def test_concurrent_checks_return_their_own_decisions() -> None:
    pack = make_pack()
    entries = [{"message": f"m{i}", "scores": zeros(q_a=0.9 if i % 2 else 0.0)} for i in range(50)]
    gate = Gate(pack, ReplayBackend(entries, pack))
    results = await asyncio.gather(
        *(gate.check_async(f"m{i}", conversation_id=str(i)) for i in range(50))
    )
    for i, d in enumerate(results):
        assert d.conversation_id == str(i)
        assert d.action == ("route" if i % 2 else "continue")


def test_from_pack_with_explicit_backend(tmp_path: Path) -> None:
    p = tmp_path / "pack.yaml"
    p.write_text(yaml.safe_dump(THREE_RULES), encoding="utf-8")
    gate = Gate.from_pack(p, backend=StaticBackend(zeros()))
    assert gate.pack.name == "three"
    assert gate.check("hi").action == "continue"


def test_from_pack_defaults_to_jev(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "pack.yaml"
    p.write_text(yaml.safe_dump(THREE_RULES), encoding="utf-8")
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    with Gate.from_pack(p) as gate:
        assert gate.backend.name == "typesafe-jev"


def test_from_pack_without_key_is_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = tmp_path / "pack.yaml"
    p.write_text(yaml.safe_dump(THREE_RULES), encoding="utf-8")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(dutygate.ConfigError, match="TYPESAFE_API_KEY"):
        Gate.from_pack(p)


def test_holding_reply_is_neutral() -> None:
    d = Gate(make_pack(), StaticBackend(zeros(q_a=0.9))).check("my lawyer will call")
    reply = default_holding_reply(d)
    assert reply == DEFAULT_HOLDING_REPLY
    for banned in ["sorry", "unsubscribed", "deleted", "refund", "days", "law", "fault"]:
        assert banned not in reply.lower()


def test_public_api_exports() -> None:
    for name in [
        "Gate",
        "evaluate",
        "evaluate_async",
        "load_policy",
        "Decision",
        "Flag",
        "ErrorInfo",
        "Pack",
        "TypeSafeJevBackend",
        "JevConfig",
        "ReplayBackend",
        "KeywordBackend",
        "BackendError",
        "PackError",
        "ConfigError",
        "default_holding_reply",
        "__version__",
    ]:
        assert hasattr(dutygate, name), name
