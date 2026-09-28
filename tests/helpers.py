"""Shared test doubles and fixtures."""

from __future__ import annotations

import copy
from typing import Any

from dutygate.backends.base import BackendRequest, BackendResult, SyncBackendBase
from dutygate.schema import Pack, load_policy

THREE_RULES: dict[str, Any] = {
    "schema_version": 1,
    "name": "three",
    "version": "1.2.3",
    "redaction": [
        {
            "name": "email",
            "pattern": r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+",
            "replacement": "[EMAIL]",
        }
    ],
    "questions": [
        {"id": "q_a", "instructions": "A?"},
        {"id": "q_b", "instructions": "B?"},
        {"id": "q_c", "instructions": "C?"},
        {"id": "q_d", "instructions": "D?"},
    ],
    "rules": [
        {
            "id": "rule-a",
            "category": "cat_a",
            "questions": ["q_a"],
            "queue": "qa",
            "priority": "urgent",
        },
        {
            "id": "rule-b",
            "category": "cat_b",
            "questions": ["q_b", "q_d"],
            "match": "all",
            "queue": "qb",
            "priority": "high",
        },
        {
            "id": "rule-c",
            "category": "cat_c",
            "questions": ["q_c", "q_d"],
            "queue": "qc",
            "priority": "normal",
            "thresholds": {"low": 0.1, "high": 0.3},
        },
    ],
}


def make_pack(**changes: Any) -> Pack:
    data = copy.deepcopy(THREE_RULES)
    data.update(changes)
    return load_policy(data)


class StaticBackend(SyncBackendBase):
    """Returns fixed scores (or raises a fixed exception) and records every request."""

    name = "static"

    def __init__(
        self,
        scores: dict[str, Any] | None = None,
        *,
        exc: Exception | None = None,
        model: str | None = "static-1",
    ) -> None:
        self.scores = scores or {}
        self.exc = exc
        self.model = model
        self.requests: list[BackendRequest] = []

    def answer(self, req: BackendRequest) -> BackendResult:
        self.requests.append(req)
        if self.exc is not None:
            raise self.exc
        return BackendResult(scores=dict(self.scores), model=self.model)


def zeros(**overrides: float) -> dict[str, float]:
    base = {"q_a": 0.0, "q_b": 0.0, "q_c": 0.0, "q_d": 0.0}
    base.update(overrides)
    return base
