"""Framework-agnostic host logic: check the message, then reply, hold, or queue a review.

Works in any web framework or message consumer: call ``handle`` (or ``handle_async``) with the
inbound message and send back ``result.reply``.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from ..decision import Decision
from ..gate import Gate
from ..holding import default_holding_reply

ReplyFn = Callable[[str], Any]
DecisionCallback = Callable[[Decision, str], Any]
HoldingFn = Callable[[Decision], Any]


@dataclass(frozen=True)
class GatedResult:
    reply: Any
    decision: Decision
    outbound_decision: Decision | None = None


def _call_sync(fn: Callable[..., Any], *args: Any) -> Any:
    result = fn(*args)
    if inspect.isawaitable(result):
        if inspect.iscoroutine(result):
            result.close()
        raise TypeError(f"{getattr(fn, '__name__', fn)!s} is async; use handle_async()")
    return result


async def _call_async(fn: Callable[..., Any], *args: Any) -> Any:
    result = fn(*args)
    if inspect.isawaitable(result):
        return await result
    return result


class GatedHandler:
    """Encodes the host contract.

    * ``continue``: the bot replies.
    * ``route``: ``on_route`` runs (create a case), then the holding reply is returned.
      The bot is never called, so it cannot improvise about the trigger.
    * ``review``: ``on_review`` runs, plus ``on_gate_failure`` when the gate could not judge
      (re-scan the message later). Then the bot replies, unless ``hold_on_review`` is set.

    Exceptions from your callbacks propagate: a failed case creation must be loud, so that the
    webhook platform retries instead of the message being silently lost.

    With ``outbound_gate``, the bot's reply is checked too (for example with the
    ``outbound-claims`` pack) before it is returned.
    """

    def __init__(
        self,
        gate: Gate,
        *,
        reply: ReplyFn,
        on_route: DecisionCallback,
        on_review: DecisionCallback,
        on_gate_failure: DecisionCallback | None = None,
        holding_reply: HoldingFn = default_holding_reply,
        hold_on_review: bool = False,
        outbound_gate: Gate | None = None,
    ) -> None:
        self.gate = gate
        self.reply = reply
        self.on_route = on_route
        self.on_review = on_review
        self.on_gate_failure = on_gate_failure
        self.holding_reply = holding_reply
        self.hold_on_review = hold_on_review
        self.outbound_gate = outbound_gate

    def handle(
        self,
        message: str,
        *,
        conversation_id: str | None = None,
        channel: str | None = None,
        recent_messages: Sequence[str] | None = None,
    ) -> GatedResult:
        decision = self.gate.check(
            message,
            conversation_id=conversation_id,
            channel=channel,
            recent_messages=recent_messages,
        )
        if decision.action == "route":
            _call_sync(self.on_route, decision, message)
            return GatedResult(_call_sync(self.holding_reply, decision), decision)
        if decision.action == "review":
            _call_sync(self.on_review, decision, message)
            if decision.error is not None and self.on_gate_failure is not None:
                _call_sync(self.on_gate_failure, decision, message)
            if self.hold_on_review:
                return GatedResult(_call_sync(self.holding_reply, decision), decision)
        bot_reply = _call_sync(self.reply, message)
        if self.outbound_gate is None:
            return GatedResult(bot_reply, decision)
        out = self.outbound_gate.check(
            bot_reply, conversation_id=conversation_id, channel=channel, recent_messages=[message]
        )
        return GatedResult(self._outbound_sync(out, bot_reply), decision, out)

    async def handle_async(
        self,
        message: str,
        *,
        conversation_id: str | None = None,
        channel: str | None = None,
        recent_messages: Sequence[str] | None = None,
    ) -> GatedResult:
        decision = await self.gate.check_async(
            message,
            conversation_id=conversation_id,
            channel=channel,
            recent_messages=recent_messages,
        )
        if decision.action == "route":
            await _call_async(self.on_route, decision, message)
            return GatedResult(await _call_async(self.holding_reply, decision), decision)
        if decision.action == "review":
            await _call_async(self.on_review, decision, message)
            if decision.error is not None and self.on_gate_failure is not None:
                await _call_async(self.on_gate_failure, decision, message)
            if self.hold_on_review:
                return GatedResult(await _call_async(self.holding_reply, decision), decision)
        bot_reply = await _call_async(self.reply, message)
        if self.outbound_gate is None:
            return GatedResult(bot_reply, decision)
        out = await self.outbound_gate.check_async(
            bot_reply,
            conversation_id=conversation_id,
            channel=channel,
            recent_messages=[message],
        )
        if out.action == "route":
            await _call_async(self.on_route, out, bot_reply)
            return GatedResult(await _call_async(self.holding_reply, out), decision, out)
        if out.action == "review":
            await _call_async(self.on_review, out, bot_reply)
            if out.error is not None and self.on_gate_failure is not None:
                await _call_async(self.on_gate_failure, out, bot_reply)
        return GatedResult(bot_reply, decision, out)

    def _outbound_sync(self, out: Decision, bot_reply: str) -> Any:
        if out.action == "route":
            _call_sync(self.on_route, out, bot_reply)
            return _call_sync(self.holding_reply, out)
        if out.action == "review":
            _call_sync(self.on_review, out, bot_reply)
            if out.error is not None and self.on_gate_failure is not None:
                _call_sync(self.on_gate_failure, out, bot_reply)
        return bot_reply
