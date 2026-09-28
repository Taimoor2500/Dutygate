"""LangGraph adapter: DutyGate as nodes in a graph.

    graph = StateGraph(DutyGateState)
    graph.add_node("dutygate", gate_node(gate, on_route=create_case))
    graph.add_node("agent", agent)
    graph.add_edge(START, "dutygate")
    graph.add_conditional_edges("dutygate", after_gate("agent"))   # END on route
    graph.add_edge("agent", END)

On ``route`` the gate node appends the holding reply and ``after_gate`` ends the graph, so the
agent never runs. ``outbound_node`` can follow the agent to check its reply and replace it in
place when it should not be sent. Both nodes support ``invoke`` and ``ainvoke``.

Requires the ``langgraph`` extra.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, MessagesState

from ..decision import Decision
from ..gate import Gate
from ..holding import default_holding_reply
from .langchain import _last_human, _text
from .webhook import _call_async, _call_sync

DecisionCallback = Callable[[Decision, str], Any]
State = dict[str, Any]


class DutyGateState(MessagesState):
    """MessagesState plus the decisions DutyGate writes. Subclass it to add your own fields."""

    dutygate: dict[str, Any] | None
    dutygate_outbound: dict[str, Any] | None


def _messages(state: State, key: str) -> list[Any]:
    messages = state.get(key)
    if not isinstance(messages, list):
        raise ValueError(f"graph state has no '{key}' message list")
    return messages


def gate_node(
    gate: Gate,
    *,
    messages_key: str = "messages",
    state_key: str = "dutygate",
    on_route: DecisionCallback | None = None,
    on_review: DecisionCallback | None = None,
    holding_reply: Callable[[Decision], str] = default_holding_reply,
) -> RunnableLambda[State, State]:
    """A node that checks the latest human message.

    Writes the decision to ``state[state_key]``. On ``route`` it also appends the holding reply
    as an AIMessage. Pair it with ``after_gate`` to skip the agent on ``route``.
    """

    def update(decision: Decision) -> State:
        out: State = {state_key: decision.to_dict()}
        if decision.action == "route":
            out[messages_key] = [AIMessage(content=holding_reply(decision))]
        return out

    def run(state: State) -> State:
        text = _last_human(_messages(state, messages_key))
        decision = gate.check(text)
        if decision.action == "route" and on_route is not None:
            _call_sync(on_route, decision, text)
        elif decision.action == "review" and on_review is not None:
            _call_sync(on_review, decision, text)
        return update(decision)

    async def arun(state: State) -> State:
        text = _last_human(_messages(state, messages_key))
        decision = await gate.check_async(text)
        if decision.action == "route" and on_route is not None:
            await _call_async(on_route, decision, text)
        elif decision.action == "review" and on_review is not None:
            await _call_async(on_review, decision, text)
        return update(decision)

    return RunnableLambda(run, afunc=arun, name="dutygate")


def after_gate(next_node: str, *, state_key: str = "dutygate") -> Callable[[State], str]:
    """Conditional-edge router: END when the gate routed the message, else ``next_node``."""

    def route(state: State) -> str:
        decision = state.get(state_key) or {}
        return str(END) if decision.get("action") == "route" else next_node

    return route


def outbound_node(
    gate: Gate,
    *,
    messages_key: str = "messages",
    state_key: str = "dutygate_outbound",
    on_route: DecisionCallback | None = None,
    on_review: DecisionCallback | None = None,
    holding_reply: Callable[[Decision], str] = default_holding_reply,
) -> RunnableLambda[State, State]:
    """A node that checks the agent's latest reply, for example with the outbound-claims pack.

    On ``route`` the reply is replaced in place (same message id) by the holding reply. The
    customer's latest message is passed as context. Does nothing if the last message is not
    an AI reply.
    """

    def prepare(state: State) -> tuple[AIMessage, str, list[str]] | None:
        messages = _messages(state, messages_key)
        if not messages or not isinstance(messages[-1], AIMessage):
            return None
        reply = messages[-1]
        earlier: list[BaseMessage] = messages[:-1]
        try:
            context = [_last_human(earlier)]
        except ValueError:
            context = []
        return reply, _text(reply.content), context

    def update(decision: Decision, reply: AIMessage) -> State:
        out: State = {state_key: decision.to_dict()}
        if decision.action == "route":
            out[messages_key] = [AIMessage(content=holding_reply(decision), id=reply.id)]
        return out

    def run(state: State) -> State:
        prepared = prepare(state)
        if prepared is None:
            return {}
        reply, text, context = prepared
        decision = gate.check(text, recent_messages=context)
        if decision.action == "route" and on_route is not None:
            _call_sync(on_route, decision, text)
        elif decision.action == "review" and on_review is not None:
            _call_sync(on_review, decision, text)
        return update(decision, reply)

    async def arun(state: State) -> State:
        prepared = prepare(state)
        if prepared is None:
            return {}
        reply, text, context = prepared
        decision = await gate.check_async(text, recent_messages=context)
        if decision.action == "route" and on_route is not None:
            await _call_async(on_route, decision, text)
        elif decision.action == "review" and on_review is not None:
            await _call_async(on_review, decision, text)
        return update(decision, reply)

    return RunnableLambda(run, afunc=arun, name="dutygate_outbound")
