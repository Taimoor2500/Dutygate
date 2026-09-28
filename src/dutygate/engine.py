"""The one place decisions are made. See SPEC.md, "Evaluation"."""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Mapping, Sequence
from typing import Any

from .backends.base import Backend, BackendRequest, BackendResult
from .decision import Action, Decision, ErrorInfo, Flag, Level, new_decision_id
from .errors import BackendError, ErrorCode
from .redact import Redactor
from .schema import Pack

logger = logging.getLogger("dutygate")

ROUND_DIGITS = 4


def check_inputs(
    message: object,
    conversation_id: object,
    channel: object,
    recent_messages: object,
) -> None:
    """Reject wrong argument types up front: these are host programming errors, not outages."""
    if not isinstance(message, str):
        raise TypeError(f"message must be str, not {type(message).__name__}")
    for name, value in (("conversation_id", conversation_id), ("channel", channel)):
        if value is not None and not isinstance(value, str):
            raise TypeError(f"{name} must be str or None, not {type(value).__name__}")
    if recent_messages is not None:
        if isinstance(recent_messages, (str, bytes)) or not isinstance(recent_messages, Sequence):
            raise TypeError("recent_messages must be a sequence of str or None")
        for item in recent_messages:
            if not isinstance(item, str):
                raise TypeError(f"recent_messages items must be str, not {type(item).__name__}")


def build_state(
    pack: Pack,
    redactor: Redactor,
    message: str,
    channel: str | None,
    recent_messages: Sequence[str] | None,
) -> dict[str, Any]:
    state: dict[str, Any] = {pack.state_field: redactor.redact(message)}
    n = pack.context.max_recent_messages
    if n and recent_messages:
        state["recent_messages"] = [redactor.redact(m) for m in list(recent_messages)[-n:]]
    if channel is not None:
        state["channel"] = channel
    return state


def validate_scores(pack: Pack, raw: Mapping[str, Any]) -> dict[str, float]:
    """All-or-nothing: every question must have a finite number in [0, 1]."""
    if not isinstance(raw, Mapping):
        raise BackendError("malformed_response", "answers are not a mapping")
    scores: dict[str, float] = {}
    for q in pack.questions:
        if q.id not in raw:
            raise BackendError("malformed_response", f"missing answer for question '{q.id}'")
        value = raw[q.id]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise BackendError(
                "malformed_response",
                f"answer for '{q.id}' is not a number ({type(value).__name__})",
            )
        value = float(value)
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise BackendError("malformed_response", f"answer for '{q.id}' is out of range")
        scores[q.id] = value
    return scores


def decide(pack: Pack, scores: Mapping[str, float]) -> tuple[Action, str | None, tuple[Flag, ...]]:
    confident: list[Flag] = []
    grey: list[Flag] = []
    for rule in pack.rules:
        values = [scores[qid] for qid in rule.questions]
        score = max(values) if rule.match == "any" else min(values)
        t = pack.thresholds_for(rule)
        level: Level
        if score >= t.high:
            level = "confident"
        elif score >= t.low:
            level = "grey"
        else:
            continue
        flag = Flag(
            category=rule.category,
            rule_id=rule.id,
            queue=rule.queue,
            priority=rule.priority,
            confidence=round(score, ROUND_DIGITS),
            level=level,
        )
        (confident if level == "confident" else grey).append(flag)
    flags = tuple(confident + grey)
    action: Action = "route" if confident else "review" if grey else "continue"
    return action, (flags[0].category if flags else None), flags


class _Evaluation:
    """Shared bookkeeping for the sync and async paths."""

    def __init__(self, pack: Pack, backend: Backend, conversation_id: str | None) -> None:
        self.pack = pack
        self.backend = backend
        self.conversation_id = conversation_id
        self.started = time.perf_counter()

    def _make(
        self,
        action: Action,
        primary: str | None,
        flags: tuple[Flag, ...],
        error: ErrorInfo | None,
        model: str | None,
    ) -> Decision:
        return Decision(
            id=new_decision_id(),
            action=action,
            primary=primary,
            flags=flags,
            error=error,
            policy={"name": self.pack.name, "version": self.pack.version},
            backend={"name": self.backend.name, "model": model},
            conversation_id=self.conversation_id,
            latency_ms=int((time.perf_counter() - self.started) * 1000),
        )

    def error(self, code: ErrorCode, message: str) -> Decision:
        return self._make(self.pack.defaults.on_error, None, (), ErrorInfo(code, message), None)

    def from_result(self, result: BackendResult) -> Decision:
        try:
            scores = validate_scores(self.pack, result.scores)
        except BackendError as exc:
            return self.error(exc.code, exc.message)
        action, primary, flags = decide(self.pack, scores)
        return self._make(action, primary, flags, None, result.model)

    def internal(self) -> Decision:
        logger.exception("dutygate internal error", extra={"pack": self.pack.name})
        return self.error("internal_error", "unexpected error inside the gate; see logs")

    def precheck(self, message: str) -> Decision | None:
        if not message.strip():
            return self._make("continue", None, (), None, None)
        limit = self.pack.limits.max_message_chars
        if len(message) > limit:
            return self.error(
                "message_too_long", f"message has {len(message)} characters; limit is {limit}"
            )
        return None


def _request(
    pack: Pack,
    redactor: Redactor | None,
    message: str,
    channel: str | None,
    recent_messages: Sequence[str] | None,
) -> BackendRequest:
    state = build_state(
        pack, redactor or Redactor(pack.redaction), message, channel, recent_messages
    )
    return BackendRequest(state=state, questions=pack.questions)


def evaluate(
    pack: Pack,
    message: str,
    backend: Backend,
    *,
    conversation_id: str | None = None,
    channel: str | None = None,
    recent_messages: Sequence[str] | None = None,
    redactor: Redactor | None = None,
) -> Decision:
    """Judge one message. Never raises for runtime failures; returns an error decision instead."""
    check_inputs(message, conversation_id, channel, recent_messages)
    ev = _Evaluation(pack, backend, conversation_id)
    try:
        early = ev.precheck(message)
        if early is not None:
            return early
        req = _request(pack, redactor, message, channel, recent_messages)
        try:
            result = backend.answer(req)
        except BackendError as exc:
            return ev.error(exc.code, exc.message)
        return ev.from_result(result)
    except Exception:
        return ev.internal()


async def evaluate_async(
    pack: Pack,
    message: str,
    backend: Backend,
    *,
    conversation_id: str | None = None,
    channel: str | None = None,
    recent_messages: Sequence[str] | None = None,
    redactor: Redactor | None = None,
) -> Decision:
    """Async twin of :func:`evaluate`."""
    check_inputs(message, conversation_id, channel, recent_messages)
    ev = _Evaluation(pack, backend, conversation_id)
    try:
        early = ev.precheck(message)
        if early is not None:
            return early
        req = _request(pack, redactor, message, channel, recent_messages)
        try:
            result = await backend.answer_async(req)
        except BackendError as exc:
            return ev.error(exc.code, exc.message)
        return ev.from_result(result)
    except Exception:
        return ev.internal()
