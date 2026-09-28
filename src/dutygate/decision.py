from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Literal, cast

Action = Literal["continue", "route", "review"]
Level = Literal["confident", "grey"]
Priority = Literal["urgent", "high", "normal", "low"]

ACTION_RANK: dict[str, int] = {"continue": 0, "review": 1, "route": 2}


@dataclass(frozen=True)
class ErrorInfo:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class Flag:
    category: str
    rule_id: str
    queue: str
    priority: Priority
    confidence: float
    level: Level

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "rule_id": self.rule_id,
            "queue": self.queue,
            "priority": self.priority,
            "confidence": self.confidence,
            "level": self.level,
        }


@dataclass(frozen=True)
class Decision:
    """The gate's verdict for one message. Serializes to the stable JSON contract."""

    id: str
    action: Action
    primary: str | None
    flags: tuple[Flag, ...]
    error: ErrorInfo | None
    policy: dict[str, str]
    backend: dict[str, str | None]
    conversation_id: str | None
    latency_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "primary": self.primary,
            "flags": [f.to_dict() for f in self.flags],
            "error": self.error.to_dict() if self.error else None,
            "policy": dict(self.policy),
            "backend": dict(self.backend),
            "conversation_id": self.conversation_id,
            "latency_ms": self.latency_ms,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Decision:
        err = d.get("error")
        return cls(
            id=d["id"],
            action=cast(Action, d["action"]),
            primary=d.get("primary"),
            flags=tuple(
                Flag(
                    category=f["category"],
                    rule_id=f["rule_id"],
                    queue=f["queue"],
                    priority=f["priority"],
                    confidence=float(f["confidence"]),
                    level=f["level"],
                )
                for f in d.get("flags", [])
            ),
            error=ErrorInfo(err["code"], err["message"]) if err else None,
            policy=dict(d["policy"]),
            backend=dict(d.get("backend", {})),
            conversation_id=d.get("conversation_id"),
            latency_ms=int(d.get("latency_ms", 0)),
        )


def new_decision_id() -> str:
    return "dec_" + uuid.uuid4().hex
