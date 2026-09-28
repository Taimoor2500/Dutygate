"""Calls the real TypeSafe API. Run with: TYPESAFE_API_KEY=... uv run pytest -m live"""

import os
from pathlib import Path

import pytest

from dutygate import Gate, TypeSafeJevBackend, load_policy
from dutygate.backends.base import BackendRequest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("TYPESAFE_API_KEY"), reason="TYPESAFE_API_KEY not set"),
]


def test_reference_pack_gets_every_answer() -> None:
    pack = load_policy(ROOT / "packs" / "legal-triggers.yaml")
    backend = TypeSafeJevBackend.from_env()
    try:
        res = backend.answer(
            BackendRequest(
                state={"customer_message": "please stop texting me"}, questions=pack.questions
            )
        )
    finally:
        backend.close()
    assert set(res.scores) == {q.id for q in pack.questions}
    assert all(0.0 <= float(v) <= 1.0 for v in res.scores.values())
    assert res.model is not None and res.model.startswith("jev")


def test_obvious_opt_out_is_flagged() -> None:
    with Gate.from_pack(ROOT / "packs" / "legal-triggers.yaml") as gate:
        d = gate.check("STOP. Unsubscribe me from these texts.", channel="sms")
    assert d.error is None, d.error
    assert d.action in ("route", "review")
    assert "opt_out" in {f.category for f in d.flags}
