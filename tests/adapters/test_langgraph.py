from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from dutygate import DEFAULT_HOLDING_REPLY, Decision, Gate
from dutygate.adapters.langgraph import DutyGateState, after_gate, gate_node, outbound_node

from ..helpers import StaticBackend, make_pack, zeros


class Agent:
    """A stand-in for an LLM agent node that records how often it ran."""

    def __init__(self, reply: str = "Happy to help!") -> None:
        self.reply = reply
        self.calls = 0

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        return {"messages": [AIMessage(self.reply)]}


def inbound(**scores: float) -> Gate:
    return Gate(make_pack(), StaticBackend(zeros(**scores)))


def outbound(**scores: float) -> Gate:
    return Gate(
        make_pack(state_field="assistant_reply", context={"max_recent_messages": 1}),
        StaticBackend(zeros(**scores)),
    )


def build(
    inbound_gate: Gate,
    agent: Agent,
    outbound_gate: Gate | None = None,
    checkpointer: Any = None,
    **node_kwargs: Any,
) -> Any:
    graph = StateGraph(DutyGateState)
    graph.add_node("dutygate", gate_node(inbound_gate, **node_kwargs))
    graph.add_node("agent", agent)
    graph.add_edge(START, "dutygate")
    graph.add_conditional_edges("dutygate", after_gate("agent"))
    if outbound_gate is None:
        graph.add_edge("agent", END)
    else:
        graph.add_node("check_reply", outbound_node(outbound_gate, **node_kwargs))
        graph.add_edge("agent", "check_reply")
        graph.add_edge("check_reply", END)
    return graph.compile(checkpointer=checkpointer)


def ask(text: str) -> dict[str, Any]:
    return {"messages": [HumanMessage(text)]}


# ---------- inbound ----------


def test_continue_runs_the_agent() -> None:
    agent = Agent()
    out = build(inbound(), agent).invoke(ask("where is my order?"))
    assert agent.calls == 1
    assert out["messages"][-1].content == "Happy to help!"
    assert out["dutygate"]["action"] == "continue"


def test_route_holds_and_the_agent_never_runs() -> None:
    agent = Agent()
    routed: list[tuple[str, str]] = []
    app = build(inbound(q_a=0.9), agent, on_route=lambda d, text: routed.append((d.action, text)))
    out = app.invoke(ask("my lawyer will call"))
    assert agent.calls == 0
    assert out["messages"][-1].content == DEFAULT_HOLDING_REPLY
    assert isinstance(out["messages"][-1], AIMessage)
    assert out["dutygate"]["primary"] == "cat_a"
    assert routed == [("route", "my lawyer will call")]


def test_review_runs_the_agent_and_queues_a_review() -> None:
    agent = Agent()
    reviewed: list[str] = []
    out = build(inbound(q_a=0.3), agent, on_review=lambda d, text: reviewed.append(text)).invoke(
        ask("hmm")
    )
    assert agent.calls == 1
    assert out["dutygate"]["action"] == "review"
    assert reviewed == ["hmm"]


def test_custom_holding_reply() -> None:
    out = build(inbound(q_a=0.9), Agent(), holding_reply=lambda d: "held").invoke(ask("x"))
    assert out["messages"][-1].content == "held"


async def test_async_graph_with_async_callbacks() -> None:
    seen: list[str] = []

    async def on_route(decision: Decision, text: str) -> None:
        seen.append(text)

    agent = Agent()
    out = await build(inbound(q_a=0.9), agent, on_route=on_route).ainvoke(ask("lawyer"))
    assert agent.calls == 0 and seen == ["lawyer"]
    assert out["messages"][-1].content == DEFAULT_HOLDING_REPLY


def test_checks_the_latest_human_message_across_turns() -> None:
    backend = StaticBackend(zeros(q_a=0.9))
    app = build(Gate(make_pack(), backend), Agent(), checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "t1"}}
    first = app.invoke(ask("my lawyer will call"), config)
    assert first["dutygate"]["action"] == "route"
    backend.scores = zeros()
    second = app.invoke(ask("ok, where is my order?"), config)
    assert second["dutygate"]["action"] == "continue"
    assert backend.requests[-1].state["customer_message"] == "ok, where is my order?"
    assert second["messages"][-1].content == "Happy to help!"


def test_multimodal_content_is_reduced_to_text() -> None:
    backend = StaticBackend(zeros())
    app = build(Gate(make_pack(), backend), Agent())
    app.invoke(
        {
            "messages": [
                HumanMessage(
                    content=[
                        {"type": "text", "text": "stop"},
                        {"type": "image_url", "image_url": {"url": "x"}},
                        {"type": "text", "text": "texting me"},
                    ]
                )
            ]
        }
    )
    assert backend.requests[0].state["customer_message"] == "stop\ntexting me"


def test_no_human_message_is_a_clear_error() -> None:
    with pytest.raises(ValueError, match="human message"):
        build(inbound(), Agent()).invoke({"messages": [AIMessage("hello")]})


# ---------- outbound ----------


def test_outbound_route_replaces_the_reply_in_place() -> None:
    routed: list[str] = []
    app = build(
        inbound(),
        Agent("Done! You've been unsubscribed."),
        outbound(q_a=0.95),
        on_route=lambda d, text: routed.append(text),
    )
    out = app.invoke(ask("stop texting me"))
    assert [m.content for m in out["messages"]] == ["stop texting me", DEFAULT_HOLDING_REPLY]
    assert out["dutygate_outbound"]["action"] == "route"
    assert routed == ["Done! You've been unsubscribed."]


def test_outbound_sees_the_customer_message_as_context() -> None:
    backend = StaticBackend(zeros())
    gate = Gate(
        make_pack(state_field="assistant_reply", context={"max_recent_messages": 1}), backend
    )
    build(inbound(), Agent("Sure."), gate).invoke(ask("can you help?"))
    assert backend.requests[0].state == {
        "assistant_reply": "Sure.",
        "recent_messages": ["can you help?"],
    }


def test_outbound_continue_keeps_the_reply() -> None:
    out = build(inbound(), Agent("Your order ships Thursday."), outbound()).invoke(ask("order?"))
    assert out["messages"][-1].content == "Your order ships Thursday."
    assert out["dutygate_outbound"]["action"] == "continue"


def test_outbound_skipped_when_inbound_routes() -> None:
    out = build(inbound(q_a=0.9), Agent(), outbound()).invoke(ask("lawyer"))
    assert out.get("dutygate_outbound") is None


def test_outbound_node_ignores_a_state_without_an_ai_reply() -> None:
    node = outbound_node(outbound())
    assert node.invoke({"messages": [HumanMessage("hi")]}) == {}


# ---------- custom keys ----------


def test_custom_state_and_messages_keys() -> None:
    from typing import Annotated, TypedDict

    from langgraph.graph.message import add_messages

    class Custom(TypedDict, total=False):
        chat: Annotated[list[Any], add_messages]
        verdict: dict[str, Any] | None

    agent_calls: list[int] = []

    def agent(state: Custom) -> dict[str, Any]:
        agent_calls.append(1)
        return {"chat": [AIMessage("hi")]}

    graph = StateGraph(Custom)
    graph.add_node(
        "dutygate", gate_node(inbound(q_a=0.9), messages_key="chat", state_key="verdict")
    )
    graph.add_node("agent", agent)
    graph.add_edge(START, "dutygate")
    graph.add_conditional_edges("dutygate", after_gate("agent", state_key="verdict"))
    graph.add_edge("agent", END)
    out = graph.compile().invoke({"chat": [HumanMessage("lawyer")]})
    assert out["verdict"]["action"] == "route" and agent_calls == []
    assert out["chat"][-1].content == DEFAULT_HOLDING_REPLY


async def test_async_outbound_route_and_review_callbacks() -> None:
    seen: list[tuple[str, str]] = []

    async def on_route(decision: Decision, text: str) -> None:
        seen.append(("route", text))

    async def on_review(decision: Decision, text: str) -> None:
        seen.append(("review", text))

    app = build(
        inbound(q_a=0.3),
        Agent("Refund processed!"),
        outbound(q_a=0.95),
        on_route=on_route,
        on_review=on_review,
    )
    out = await app.ainvoke(ask("hmm"))
    assert seen == [("review", "hmm"), ("route", "Refund processed!")]
    assert out["messages"][-1].content == DEFAULT_HOLDING_REPLY


def test_outbound_review_keeps_the_reply_and_calls_back() -> None:
    reviewed: list[str] = []
    out = build(
        inbound(),
        Agent("Maybe some credit?"),
        outbound(q_a=0.3),
        on_review=lambda d, text: reviewed.append(text),
    ).invoke(ask("hi"))
    assert out["messages"][-1].content == "Maybe some credit?"
    assert reviewed == ["Maybe some credit?"]


async def test_outbound_without_a_customer_message_has_no_context() -> None:
    backend = StaticBackend(zeros())
    gate = Gate(
        make_pack(state_field="assistant_reply", context={"max_recent_messages": 1}), backend
    )
    node = outbound_node(gate)
    assert (await node.ainvoke({"messages": [AIMessage("hello")]}))["dutygate_outbound"]
    assert backend.requests[0].state == {"assistant_reply": "hello"}
    assert await node.ainvoke({"messages": [HumanMessage("hi")]}) == {}


def test_missing_messages_key_is_a_clear_error() -> None:
    with pytest.raises(ValueError, match="'chat' message list"):
        gate_node(inbound(), messages_key="chat").invoke({"messages": []})


def test_after_gate_without_a_decision_continues() -> None:
    assert after_gate("agent")({"messages": []}) == "agent"
