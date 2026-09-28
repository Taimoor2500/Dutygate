"""Reads conformance/cases.json and normalizes decisions for comparison."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from dutygate import Pack, ReplayBackend, load_policy

ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = ROOT / "conformance" / "cases.json"


@dataclass(frozen=True)
class Case:
    name: str
    pack: str
    input: dict[str, Any]
    expected: dict[str, Any]
    expect_state: dict[str, Any] | None


@cache
def document() -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    return doc


def cases() -> list[Case]:
    return [
        Case(c["name"], c["pack"], c["input"], c["expected"], c.get("expect_state"))
        for c in document()["cases"]
    ]


@cache
def pack(name: str) -> Pack:
    return load_policy(ROOT / document()["packs"][name])


def replay_backend(name: str) -> ReplayBackend:
    return ReplayBackend.from_conformance(CASES_PATH, pack(name))


def normalize(decision: dict[str, Any]) -> dict[str, Any]:
    """Reduce a Decision dict to the fields conformance compares."""
    err = decision.get("error")
    return {
        "action": decision["action"],
        "primary": decision["primary"],
        "flags": decision["flags"],
        "error_code": err["code"] if err else None,
        "policy": decision["policy"],
        "backend_name": decision["backend"]["name"],
        "conversation_id": decision.get("conversation_id"),
    }
