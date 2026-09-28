"""A LangGraph support agent with DutyGate before and after the agent node.

    pip install 'dutygate[langgraph]'
    TYPESAFE_API_KEY=... python graph.py "pls stop texting me"

Offline (conformance fixtures, fake model):
    DUTYGATE_BACKEND=replay DUTYGATE_FIXTURES=../../conformance/cases.json \
    python graph.py "pls stop texting me"
"""

from __future__ import annotations

import os
import sys
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from dutygate import Decision, Gate, ReplayBackend, load_policy
from dutygate.adapters.langgraph import DutyGateState, after_gate, gate_node, outbound_node

CASES: list[dict[str, Any]] = []  # stand-in for your ticketing system


def load_gate(pack_name: str) -> Gate:
    if os.environ.get("DUTYGATE_BACKEND") == "replay":
        pack = load_policy(pack_name)
        return Gate(pack, ReplayBackend.from_conformance(os.environ["DUTYGATE_FIXTURES"], pack))
    return Gate.from_pack(pack_name)  # TypeSafe Jev, configured from the environment


def create_case(decision: Decision, text: str) -> None:
    for flag in decision.flags:
        CASES.append({"queue": flag.queue, "category": flag.category, "text": text})


def default_model() -> BaseChatModel:
    # Swap in your real LangChain chat model here.
    return FakeListChatModel(responses=["Happy to help with that!"])


def build_graph(model: BaseChatModel, inbound: Gate, outbound: Gate | None = None) -> Any:
    def agent(state: DutyGateState) -> dict[str, Any]:
        system = SystemMessage("You are a helpful support assistant.")
        return {"messages": [model.invoke([system, *state["messages"]])]}

    graph = StateGraph(DutyGateState)
    graph.add_node("dutygate", gate_node(inbound, on_route=create_case))
    graph.add_node("agent", agent)
    graph.add_edge(START, "dutygate")
    graph.add_conditional_edges("dutygate", after_gate("agent"))
    if outbound is None:
        graph.add_edge("agent", END)
    else:
        graph.add_node("check_reply", outbound_node(outbound, on_route=create_case))
        graph.add_edge("agent", "check_reply")
        graph.add_edge("check_reply", END)
    return graph.compile()


if __name__ == "__main__":
    app = build_graph(default_model(), load_gate("legal-triggers"))
    message = sys.argv[1] if len(sys.argv) > 1 else "where is my order?"
    result = app.invoke({"messages": [HumanMessage(message)]})
    print(result["messages"][-1].content)
    if CASES:
        print("case created:", CASES[-1])
