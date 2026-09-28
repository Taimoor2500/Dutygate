from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

from ..decision import Decision


class GateMetrics:
    """Prometheus metrics in a registry owned by one app (so tests and apps never collide)."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.decisions = Counter(
            "dutygate_decisions",
            "Decisions returned, by pack and action.",
            ("action", "pack"),
            registry=self.registry,
        )
        self.errors = Counter(
            "dutygate_errors",
            "Decisions that carry an error, by pack and error code.",
            ("code", "pack"),
            registry=self.registry,
        )
        self.audit_failures = Counter(
            "dutygate_audit_failures",
            "Audit records that could not be written (the decision was still returned).",
            registry=self.registry,
        )
        self.latency = Histogram(
            "dutygate_decision_seconds",
            "Time to produce a decision, including the backend call.",
            ("pack",),
            buckets=(0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
            registry=self.registry,
        )

    def observe(self, pack: str, decision: Decision, seconds: float) -> None:
        self.decisions.labels(action=decision.action, pack=pack).inc()
        if decision.error is not None:
            self.errors.labels(code=decision.error.code, pack=pack).inc()
        self.latency.labels(pack=pack).observe(seconds)

    def render(self) -> bytes:
        return generate_latest(self.registry)
