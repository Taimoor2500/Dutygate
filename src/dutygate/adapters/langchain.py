"""LangChain adapter: gate a Runnable (chain, agent or chat model) before it runs.

    from dutygate.adapters.langchain import with_legal_gate
    safe_chain = with_legal_gate(chain, gate, on_route=create_case)

A callback handler cannot do this job: callbacks observe a chain, they cannot stop it. This
wrapper checks the message first and, on ``route``, returns the holding reply without running
the chain at all.

Requires the ``langchain`` extra (``langchain-core``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.prompt_values import PromptValue
from langchain_core.runnables import Runnable, RunnableConfig

from ..decision import Decision
from ..gate import Gate
from ..holding import default_holding_reply
from .webhook import _call_async, _call_sync

HUMAN_ROLES = frozenset({"human", "user"})


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            p if isinstance(p, str) else p.get("text", "")
            for p in content
            if isinstance(p, str) or (isinstance(p, dict) and p.get("type") == "text")
        ]
        return "\n".join(p for p in parts if p)
    raise ValueError(f"unsupported message content: {type(content).__name__}")


def _last_human(messages: list[Any]) -> str:
    for m in reversed(messages):
        if isinstance(m, BaseMessage) and m.type == "human":
            return _text(m.content)
        if isinstance(m, tuple) and len(m) == 2 and m[0] in HUMAN_ROLES:
            return _text(m[1])
        if isinstance(m, dict) and m.get("role") in HUMAN_ROLES:
            return _text(m.get("content", ""))
    raise ValueError("no human message found in the input")


def _is_messages(value: Any) -> bool:
    return isinstance(value, (list, PromptValue))


def _output_is_message(runnable: Runnable[Any, Any]) -> bool | None:
    """True/False when the runnable declares a message/str output type, None when unknown."""
    try:
        out = runnable.OutputType
    except Exception:
        return None
    if out is str:
        return False
    if isinstance(out, type) and issubclass(out, BaseMessage):
        return True
    return True if "langchain_core.messages" in repr(out) else None


def _unwrap(value: Any, input_key: str | None) -> Any:
    if isinstance(value, dict):
        if input_key is None:
            raise ValueError("dict input needs input_key= to say which field holds the message")
        if input_key not in value:
            raise ValueError(f"input has no '{input_key}' field")
        return value[input_key]
    return value


def extract_message(value: Any, input_key: str | None = None) -> str:
    """Find the customer's text in a Runnable input."""
    inner = _unwrap(value, input_key)
    if isinstance(inner, str):
        return inner
    if isinstance(inner, PromptValue):
        return _last_human(inner.to_messages())
    if isinstance(inner, list):
        return _last_human(inner)
    raise ValueError(f"cannot find a message in input of type {type(inner).__name__}")


class LegalGateRunnable(Runnable[Any, Any]):
    def __init__(
        self,
        runnable: Runnable[Any, Any],
        gate: Gate,
        *,
        input_key: str | None = None,
        on_route: Callable[[Decision, str], Any] | None = None,
        on_review: Callable[[Decision, str], Any] | None = None,
        holding_reply: Callable[[Decision], str] = default_holding_reply,
        as_message: bool | None = None,
    ) -> None:
        self.runnable = runnable
        self.as_message = as_message if as_message is not None else _output_is_message(runnable)
        self.gate = gate
        self.input_key = input_key
        self.on_route = on_route
        self.on_review = on_review
        self.holding_reply = holding_reply

    def _held(self, value: Any, decision: Decision) -> Any:
        text = self.holding_reply(decision)
        as_message = self.as_message
        if as_message is None:  # unknown output type: mirror the input's shape
            as_message = _is_messages(_unwrap(value, self.input_key))
        return AIMessage(content=text) if as_message else text

    def _decide(self, value: Any) -> tuple[Decision, str]:
        message = extract_message(value, self.input_key)
        decision = self.gate.check(message)
        if decision.action == "route" and self.on_route is not None:
            _call_sync(self.on_route, decision, message)
        elif decision.action == "review" and self.on_review is not None:
            _call_sync(self.on_review, decision, message)
        return decision, message

    async def _adecide(self, value: Any) -> tuple[Decision, str]:
        message = extract_message(value, self.input_key)
        decision = await self.gate.check_async(message)
        if decision.action == "route" and self.on_route is not None:
            await _call_async(self.on_route, decision, message)
        elif decision.action == "review" and self.on_review is not None:
            await _call_async(self.on_review, decision, message)
        return decision, message

    def invoke(self, input: Any, config: RunnableConfig | None = None, **kwargs: Any) -> Any:
        decision, _ = self._decide(input)
        if decision.action == "route":
            return self._held(input, decision)
        return self.runnable.invoke(input, config, **kwargs)

    async def ainvoke(self, input: Any, config: RunnableConfig | None = None, **kwargs: Any) -> Any:
        decision, _ = await self._adecide(input)
        if decision.action == "route":
            return self._held(input, decision)
        return await self.runnable.ainvoke(input, config, **kwargs)

    def stream(
        self, input: Any, config: RunnableConfig | None = None, **kwargs: Any | None
    ) -> Iterator[Any]:
        decision, _ = self._decide(input)
        if decision.action == "route":
            yield self._held(input, decision)
            return
        yield from self.runnable.stream(input, config, **kwargs)

    async def astream(
        self, input: Any, config: RunnableConfig | None = None, **kwargs: Any | None
    ) -> AsyncIterator[Any]:
        decision, _ = await self._adecide(input)
        if decision.action == "route":
            yield self._held(input, decision)
            return
        async for chunk in self.runnable.astream(input, config, **kwargs):
            yield chunk


def with_legal_gate(
    runnable: Runnable[Any, Any],
    gate: Gate,
    *,
    input_key: str | None = None,
    on_route: Callable[[Decision, str], Any] | None = None,
    on_review: Callable[[Decision, str], Any] | None = None,
    holding_reply: Callable[[Decision], str] = default_holding_reply,
    as_message: bool | None = None,
) -> LegalGateRunnable:
    """Wrap ``runnable`` so every input is checked by ``gate`` before it runs.

    On ``route`` the holding reply is returned as an ``AIMessage`` when the runnable produces
    messages (a chat model) and as ``str`` otherwise; ``as_message`` forces either.
    """
    return LegalGateRunnable(
        runnable,
        gate,
        input_key=input_key,
        on_route=on_route,
        on_review=on_review,
        holding_reply=holding_reply,
        as_message=as_message,
    )
