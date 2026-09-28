from typing import Any

import pytest

from dutygate import DEFAULT_HOLDING_REPLY, Decision, Gate
from dutygate.adapters.webhook import GatedHandler
from dutygate.errors import BackendError

from ..helpers import StaticBackend, make_pack, zeros


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any, Any]] = []

    def reply(self, message: str) -> str:
        self.calls.append(("reply", None, message))
        return f"bot: {message}"

    def route(self, decision: Decision, message: str) -> None:
        self.calls.append(("route", decision.action, message))

    def review(self, decision: Decision, message: str) -> None:
        self.calls.append(("review", decision.action, message))

    def failure(self, decision: Decision, message: str) -> None:
        self.calls.append(("failure", decision.error.code if decision.error else None, message))

    def names(self) -> list[str]:
        return [c[0] for c in self.calls]


def handler(
    scores: dict[str, float] | None = None, *, exc: Exception | None = None, **kw: Any
) -> tuple[GatedHandler, Recorder]:
    rec = Recorder()
    gate = Gate(make_pack(), StaticBackend(scores or zeros(), exc=exc))
    h = GatedHandler(
        gate,
        reply=rec.reply,
        on_route=rec.route,
        on_review=rec.review,
        on_gate_failure=rec.failure,
        **kw,
    )
    return h, rec


def test_continue_replies() -> None:
    h, rec = handler()
    res = h.handle("where is my order?")
    assert res.reply == "bot: where is my order?"
    assert res.decision.action == "continue"
    assert res.outbound_decision is None
    assert rec.names() == ["reply"]


def test_route_holds_and_never_calls_bot() -> None:
    h, rec = handler(zeros(q_a=0.9))
    res = h.handle("my lawyer will call")
    assert res.reply == DEFAULT_HOLDING_REPLY
    assert rec.calls == [("route", "route", "my lawyer will call")]


def test_review_replies_and_queues_review() -> None:
    h, rec = handler(zeros(q_a=0.3))
    res = h.handle("hmm")
    assert res.reply == "bot: hmm"
    assert rec.names() == ["review", "reply"]


def test_hold_on_review() -> None:
    h, rec = handler(zeros(q_a=0.3), hold_on_review=True)
    res = h.handle("hmm")
    assert res.reply == DEFAULT_HOLDING_REPLY
    assert rec.names() == ["review"]


def test_gate_error_calls_review_and_failure() -> None:
    h, rec = handler(exc=BackendError("backend_timeout", "slow"))
    res = h.handle("anything")
    assert res.decision.error is not None
    assert rec.calls[:2] == [
        ("review", "review", "anything"),
        ("failure", "backend_timeout", "anything"),
    ]
    assert res.reply == "bot: anything"


def test_custom_holding_reply() -> None:
    h, _ = handler(zeros(q_a=0.9), holding_reply=lambda d: f"held:{d.primary}")
    assert h.handle("x").reply == "held:cat_a"


def test_callback_exception_propagates() -> None:
    def broken(decision: Decision, message: str) -> None:
        raise RuntimeError("ticketing down")

    gate = Gate(make_pack(), StaticBackend(zeros(q_a=0.9)))
    h = GatedHandler(gate, reply=lambda m: m, on_route=broken, on_review=lambda d, m: None)
    with pytest.raises(RuntimeError, match="ticketing down"):
        h.handle("x")


def test_passes_metadata_to_gate() -> None:
    backend = StaticBackend(zeros())
    gate = Gate(make_pack(), backend)
    h = GatedHandler(
        gate, reply=lambda m: m, on_route=lambda d, m: None, on_review=lambda d, m: None
    )
    res = h.handle("hi", conversation_id="c_1", channel="sms")
    assert res.decision.conversation_id == "c_1"
    assert backend.requests[0].state["channel"] == "sms"


def test_outbound_route_replaces_reply() -> None:
    rec = Recorder()
    inbound = Gate(make_pack(), StaticBackend(zeros()))
    outbound = Gate(make_pack(state_field="assistant_reply"), StaticBackend(zeros(q_a=0.95)))
    h = GatedHandler(
        inbound, reply=rec.reply, on_route=rec.route, on_review=rec.review, outbound_gate=outbound
    )
    res = h.handle("cancel my plan")
    assert res.reply == DEFAULT_HOLDING_REPLY
    assert res.outbound_decision is not None and res.outbound_decision.action == "route"
    assert rec.calls == [
        ("reply", None, "cancel my plan"),
        ("route", "route", "bot: cancel my plan"),
    ]


def test_outbound_sees_customer_message_as_context() -> None:
    out_backend = StaticBackend(zeros())
    outbound = Gate(
        make_pack(state_field="assistant_reply", context={"max_recent_messages": 1}), out_backend
    )
    h = GatedHandler(
        Gate(make_pack(), StaticBackend(zeros())),
        reply=lambda m: "Done!",
        on_route=lambda d, m: None,
        on_review=lambda d, m: None,
        outbound_gate=outbound,
    )
    h.handle("unsubscribe me")
    assert out_backend.requests[0].state == {
        "assistant_reply": "Done!",
        "recent_messages": ["unsubscribe me"],
    }


def test_outbound_review_keeps_reply() -> None:
    rec = Recorder()
    outbound = Gate(make_pack(state_field="assistant_reply"), StaticBackend(zeros(q_a=0.3)))
    h = GatedHandler(
        Gate(make_pack(), StaticBackend(zeros())),
        reply=rec.reply,
        on_route=rec.route,
        on_review=rec.review,
        outbound_gate=outbound,
    )
    res = h.handle("hi")
    assert res.reply == "bot: hi"
    assert rec.names() == ["reply", "review"]


def test_outbound_skipped_when_inbound_routes() -> None:
    out_backend = StaticBackend(zeros())
    h = GatedHandler(
        Gate(make_pack(), StaticBackend(zeros(q_a=0.9))),
        reply=lambda m: m,
        on_route=lambda d, m: None,
        on_review=lambda d, m: None,
        outbound_gate=Gate(make_pack(), out_backend),
    )
    assert h.handle("x").outbound_decision is None
    assert out_backend.requests == []


async def test_async_awaits_callbacks() -> None:
    seen: list[str] = []

    async def reply(message: str) -> str:
        seen.append("reply")
        return "async bot"

    async def on_review(decision: Decision, message: str) -> None:
        seen.append("review")

    h = GatedHandler(
        Gate(make_pack(), StaticBackend(zeros(q_a=0.3))),
        reply=reply,
        on_route=lambda d, m: None,
        on_review=on_review,
    )
    res = await h.handle_async("hmm")
    assert res.reply == "async bot"
    assert seen == ["review", "reply"]


async def test_async_route_with_async_holding_reply() -> None:
    async def holding(decision: Decision) -> str:
        return "async hold"

    routed: list[str] = []

    async def on_route(decision: Decision, message: str) -> None:
        routed.append(message)

    h = GatedHandler(
        Gate(make_pack(), StaticBackend(zeros(q_a=0.9))),
        reply=lambda m: m,
        on_route=on_route,
        on_review=lambda d, m: None,
        holding_reply=holding,
    )
    res = await h.handle_async("lawyer")
    assert res.reply == "async hold" and routed == ["lawyer"]


async def test_async_outbound() -> None:
    outbound = Gate(make_pack(state_field="assistant_reply"), StaticBackend(zeros(q_a=0.9)))
    h = GatedHandler(
        Gate(make_pack(), StaticBackend(zeros())),
        reply=lambda m: "Refunded!",
        on_route=lambda d, m: None,
        on_review=lambda d, m: None,
        outbound_gate=outbound,
    )
    res = await h.handle_async("refund?")
    assert res.reply == DEFAULT_HOLDING_REPLY


def test_sync_handle_rejects_async_callbacks() -> None:
    async def reply(message: str) -> str:
        return "x"

    h = GatedHandler(
        Gate(make_pack(), StaticBackend(zeros())),
        reply=reply,
        on_route=lambda d, m: None,
        on_review=lambda d, m: None,
    )
    with pytest.raises(TypeError, match="handle_async"):
        h.handle("hi")
