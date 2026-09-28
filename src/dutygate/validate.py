"""Checks that need the whole pack, beyond what the pydantic models enforce field by field."""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .schema import Pack

RESERVED_STATE_FIELDS = frozenset({"recent_messages", "channel"})


def _duplicates(values: list[str]) -> list[str]:
    return [v for v, n in Counter(values).items() if n > 1]


def semantic_errors(pack: Pack) -> list[str]:
    errors: list[str] = []
    for qid in _duplicates([q.id for q in pack.questions]):
        errors.append(f"questions: duplicate question id '{qid}'")
    for rid in _duplicates([r.id for r in pack.rules]):
        errors.append(f"rules: duplicate rule id '{rid}'")
    for name in _duplicates([r.name for r in pack.redaction]):
        errors.append(f"redaction: duplicate redaction name '{name}'")

    known = {q.id for q in pack.questions}
    for rule in pack.rules:
        for qid in rule.questions:
            if qid not in known:
                errors.append(f"rules.{rule.id}: references unknown question '{qid}'")
        for qid in _duplicates(list(rule.questions)):
            errors.append(f"rules.{rule.id}: lists question '{qid}' twice")

    for red in pack.redaction:
        try:
            re.compile(red.pattern)
        except re.error as exc:
            errors.append(f"redaction.{red.name}: invalid regex: {exc}")

    if pack.state_field in RESERVED_STATE_FIELDS:
        errors.append(f"state_field: '{pack.state_field}' is reserved; choose another name")
    return errors


def semantic_warnings(pack: Pack) -> list[str]:
    from .schema import PRIORITY_RANK

    warnings: list[str] = []
    used = {qid for r in pack.rules for qid in r.questions}
    for q in pack.questions:
        if q.id not in used:
            warnings.append(f"questions.{q.id}: not used by any rule (still sent to the backend)")

    if pack.defaults.on_error == "continue":
        warnings.append("defaults.on_error is 'continue': the gate fails open when it cannot judge")

    worst_so_far = -1
    for rule in pack.rules:
        rank = PRIORITY_RANK[rule.priority]
        if rank < worst_so_far:
            warnings.append(
                f"rules.{rule.id}: priority '{rule.priority}' comes after a lower-priority rule; "
                "rule order decides which flag is primary"
            )
        worst_so_far = max(worst_so_far, rank)

    if pack.defaults.thresholds.low == pack.defaults.thresholds.high:
        warnings.append("defaults.thresholds: low == high, so there is no grey zone (no reviews)")
    for rule in pack.rules:
        if rule.thresholds and rule.thresholds.low == rule.thresholds.high:
            warnings.append(f"rules.{rule.id}: low == high, so there is no grey zone for this rule")

    for red in pack.redaction:
        if re.compile(red.pattern).match("") is not None:
            warnings.append(f"redaction.{red.name}: pattern matches the empty string")
    return warnings
