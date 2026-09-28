"""A LangChain chat bot with DutyGate in front of the model.

    pip install 'dutygate[langchain]'
    TYPESAFE_API_KEY=... python bot.py "pls stop texting me"

Offline (conformance fixtures, fake model):
    DUTYGATE_BACKEND=replay DUTYGATE_FIXTURES=../../conformance/cases.json \
    DUTYGATE_PACK=../../packs/legal-triggers.yaml python bot.py "pls stop texting me"
"""

from __future__ import annotations

import os
import sys
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

from dutygate import Decision, Gate, ReplayBackend, load_policy
from dutygate.adapters.langchain import with_legal_gate

CASES: list[dict[str, Any]] = []


def load_gate() -> Gate:
    pack_path = os.environ.get("DUTYGATE_PACK", "packs/legal-triggers.yaml")
    if os.environ.get("DUTYGATE_BACKEND") == "replay":
        pack = load_policy(pack_path)
        return Gate(pack, ReplayBackend.from_conformance(os.environ["DUTYGATE_FIXTURES"], pack))
    return Gate.from_pack(pack_path)


def create_case(decision: Decision, message: str) -> None:
    CASES.append({"queue": decision.flags[0].queue, "category": decision.primary})


def build_bot(model: BaseChatModel, gate: Gate) -> Runnable[Any, Any]:
    prompt = ChatPromptTemplate.from_messages(
        [("system", "You are a helpful support assistant."), ("human", "{input}")]
    )
    # The gate sees the raw customer message (input_key="input") before the prompt is built.
    return with_legal_gate(prompt | model, gate, input_key="input", on_route=create_case)


def default_model() -> BaseChatModel:
    # Swap in your real LangChain chat model here.
    return FakeListChatModel(responses=["Happy to help with that!"])


if __name__ == "__main__":
    bot = build_bot(default_model(), load_gate())
    reply = bot.invoke({"input": sys.argv[1] if len(sys.argv) > 1 else "where is my order?"})
    print(getattr(reply, "content", reply))
    if CASES:
        print("case created:", CASES[-1])
