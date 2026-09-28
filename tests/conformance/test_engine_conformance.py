from typing import Any

import pytest

from dutygate import BackendRequest, BackendResult, evaluate, load_policy_with_warnings

from .loader import ROOT, Case, cases, document, normalize, pack, replay_backend

CASES = cases()


class SpyBackend:
    """Wraps a backend and records the state it was sent."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.name = inner.name
        self.states: list[dict[str, Any]] = []

    def answer(self, req: BackendRequest) -> BackendResult:
        self.states.append(req.state)
        result: BackendResult = self.inner.answer(req)
        return result

    async def answer_async(self, req: BackendRequest) -> BackendResult:
        return self.answer(req)

    def close(self) -> None: ...

    async def aclose(self) -> None: ...


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_engine_reproduces_case(case: Case) -> None:
    spy = SpyBackend(replay_backend(case.pack))
    inp = case.input
    decision = evaluate(
        pack(case.pack),
        inp["message"],
        spy,
        conversation_id=inp.get("conversation_id"),
        channel=inp.get("channel"),
        recent_messages=inp.get("recent_messages"),
    )
    assert normalize(decision.to_dict()) == case.expected
    if case.expect_state is not None:
        assert spy.states == [case.expect_state]


def test_suite_is_broad_enough() -> None:
    assert len(CASES) >= 30
    codes = {c.expected["error_code"] for c in CASES}
    assert {
        "backend_timeout",
        "backend_unavailable",
        "backend_auth",
        "backend_rejected",
        "malformed_response",
        "message_too_long",
    } <= codes
    assert {"continue", "route", "review"} == {c.expected["action"] for c in CASES}


@pytest.mark.parametrize("name", sorted(document()["packs"]))
def test_conformance_packs_load_without_warnings(name: str) -> None:
    _, warnings = load_policy_with_warnings(ROOT / document()["packs"][name])
    assert warnings == []
