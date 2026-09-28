from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.prompt_values import ChatPromptValue
from langchain_core.runnables import RunnableLambda

from dutygate import DEFAULT_HOLDING_REPLY, Decision, Gate
from dutygate.adapters.langchain import extract_message, with_legal_gate

from ..helpers import StaticBackend, make_pack, zeros


class Counter:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, value: Any) -> str:
        self.calls += 1
        return "chain output"


def gate(**scores: float) -> Gate:
    return Gate(make_pack(), StaticBackend(zeros(**scores)))


def test_continue_invokes_chain() -> None:
    chain = Counter()
    gated = with_legal_gate(RunnableLambda(chain), gate())
    assert gated.invoke("where is my order?") == "chain output"
    assert chain.calls == 1


def test_route_skips_chain_and_returns_holding_reply() -> None:
    chain = Counter()
    routed: list[Decision] = []
    gated = with_legal_gate(
        RunnableLambda(chain), gate(q_a=0.9), on_route=lambda d, m: routed.append(d)
    )
    assert gated.invoke("my lawyer") == DEFAULT_HOLDING_REPLY
    assert chain.calls == 0
    assert routed[0].action == "route"


def test_route_with_messages_returns_ai_message_when_output_type_unknown() -> None:
    gated = with_legal_gate(RunnableLambda(lambda v: v), gate(q_a=0.9))
    out = gated.invoke([SystemMessage("be nice"), HumanMessage("my lawyer")])
    assert isinstance(out, AIMessage) and out.content == DEFAULT_HOLDING_REPLY


def test_review_invokes_chain_and_callback() -> None:
    chain = Counter()
    reviewed: list[str] = []
    gated = with_legal_gate(
        RunnableLambda(chain), gate(q_a=0.3), on_review=lambda d, m: reviewed.append(m)
    )
    assert gated.invoke("hmm") == "chain output"
    assert chain.calls == 1 and reviewed == ["hmm"]


def test_custom_holding_reply() -> None:
    gated = with_legal_gate(
        RunnableLambda(Counter()), gate(q_a=0.9), holding_reply=lambda d: "we'll be in touch"
    )
    assert gated.invoke("x") == "we'll be in touch"


async def test_ainvoke() -> None:
    chain = Counter()
    gated = with_legal_gate(RunnableLambda(chain), gate())
    assert await gated.ainvoke("hi") == "chain output"
    routed = with_legal_gate(RunnableLambda(chain), gate(q_a=0.9))
    assert await routed.ainvoke("x") == DEFAULT_HOLDING_REPLY
    assert chain.calls == 1


async def test_async_callbacks_awaited() -> None:
    seen: list[str] = []

    async def on_route(d: Decision, m: str) -> None:
        seen.append(m)

    gated = with_legal_gate(RunnableLambda(Counter()), gate(q_a=0.9), on_route=on_route)
    await gated.ainvoke("lawyer")
    assert seen == ["lawyer"]


def test_stream() -> None:
    def gen(value: Any) -> Any:
        yield "a"
        yield "b"

    chain = RunnableLambda(gen)
    assert list(with_legal_gate(chain, gate()).stream("hi")) == ["a", "b"]
    assert list(with_legal_gate(chain, gate(q_a=0.9)).stream("x")) == [DEFAULT_HOLDING_REPLY]


async def test_astream() -> None:
    async def agen(value: Any) -> Any:
        yield "a"
        yield "b"

    chain = RunnableLambda(agen)
    out = [c async for c in with_legal_gate(chain, gate()).astream("hi")]
    assert out == ["a", "b"]
    held = [c async for c in with_legal_gate(chain, gate(q_a=0.9)).astream("x")]
    assert held == [DEFAULT_HOLDING_REPLY]


def test_composes_in_a_pipe() -> None:
    upper = RunnableLambda(lambda s: s.upper())
    chain = with_legal_gate(RunnableLambda(lambda s: f"bot:{s}"), gate()) | upper
    assert chain.invoke("hi") == "BOT:HI"


def test_batch() -> None:
    gated = with_legal_gate(RunnableLambda(lambda s: f"bot:{s}"), gate())
    assert gated.batch(["a", "b"]) == ["bot:a", "bot:b"]


# ---------- message extraction ----------


@pytest.mark.parametrize(
    ("value", "key", "expected"),
    [
        ("plain text", None, "plain text"),
        ({"input": "from dict"}, "input", "from dict"),
        ({"question": "custom key"}, "question", "custom key"),
        ([HumanMessage("first"), AIMessage("reply"), HumanMessage("last")], None, "last"),
        ([("system", "rules"), ("human", "tuple form")], None, "tuple form"),
        ([{"role": "user", "content": "dict form"}], None, "dict form"),
        ({"messages": [HumanMessage("nested")]}, "messages", "nested"),
        (
            [
                HumanMessage(
                    content=[
                        {"type": "text", "text": "multi"},
                        {"type": "image_url", "image_url": {"url": "x"}},
                        {"type": "text", "text": "part"},
                    ]
                )
            ],
            None,
            "multi\npart",
        ),
        (ChatPromptValue(messages=[HumanMessage("prompt value")]), None, "prompt value"),
    ],
)
def test_extract_message(value: Any, key: str | None, expected: str) -> None:
    assert extract_message(value, key) == expected


@pytest.mark.parametrize(
    ("value", "key"),
    [
        ([AIMessage("only ai")], None),
        ({"other": "x"}, "input"),
        (42, None),
        ({"input": 3}, "input"),
    ],
)
def test_extract_message_errors(value: Any, key: str | None) -> None:
    with pytest.raises(ValueError):
        extract_message(value, key)


def test_dict_input_without_key_needs_input_key() -> None:
    gated = with_legal_gate(RunnableLambda(Counter()), gate())
    with pytest.raises(ValueError, match="input_key"):
        gated.invoke({"input": "hi"})
    assert (
        with_legal_gate(RunnableLambda(Counter()), gate(), input_key="input").invoke(
            {"input": "hi"}
        )
        == "chain output"
    )


def _prompt_model() -> Any:
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    from langchain_core.prompts import ChatPromptTemplate

    prompt = ChatPromptTemplate.from_messages([("human", "{input}")])
    return prompt | FakeListChatModel(responses=["ok"])


def test_holding_reply_matches_chat_model_output_type() -> None:
    out = with_legal_gate(_prompt_model(), gate(q_a=0.9), input_key="input").invoke(
        {"input": "lawyer"}
    )
    assert isinstance(out, AIMessage) and out.content == DEFAULT_HOLDING_REPLY


def test_holding_reply_matches_str_output_type() -> None:
    from langchain_core.output_parsers import StrOutputParser

    chain = _prompt_model() | StrOutputParser()
    out = with_legal_gate(chain, gate(q_a=0.9), input_key="input").invoke({"input": "lawyer"})
    assert out == DEFAULT_HOLDING_REPLY


def test_as_message_override() -> None:
    out = with_legal_gate(RunnableLambda(Counter()), gate(q_a=0.9), as_message=True).invoke("x")
    assert isinstance(out, AIMessage)
    out = with_legal_gate(
        _prompt_model(), gate(q_a=0.9), input_key="input", as_message=False
    ).invoke({"input": "x"})
    assert out == DEFAULT_HOLDING_REPLY
