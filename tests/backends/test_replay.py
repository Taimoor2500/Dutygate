import json
from pathlib import Path
from typing import Any

import pytest

from dutygate.backends.base import BackendRequest
from dutygate.backends.replay import ReplayBackend
from dutygate.errors import BackendError, PackError
from dutygate.schema import Pack, load_policy

PACK: dict[str, Any] = {
    "schema_version": 1,
    "name": "mini",
    "version": "0.1.0",
    "redaction": [
        {
            "name": "email",
            "pattern": r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+",
            "replacement": "[EMAIL]",
        }
    ],
    "questions": [{"id": "q_optout", "instructions": "Stop messages?"}],
    "rules": [
        {
            "id": "opt-out",
            "category": "opt_out",
            "questions": ["q_optout"],
            "queue": "compliance",
            "priority": "high",
        }
    ],
}


@pytest.fixture
def pack() -> Pack:
    return load_policy(PACK)


def req(pack: Pack, message: str) -> BackendRequest:
    return BackendRequest(state={"customer_message": message}, questions=pack.questions)


def test_scores_looked_up_after_redaction(pack: Pack) -> None:
    b = ReplayBackend([{"message": "stop mailing x@y.com", "scores": {"q_optout": 0.9}}], pack)
    res = b.answer(req(pack, "stop mailing [EMAIL]"))
    assert res.scores == {"q_optout": 0.9}
    assert res.model == "replay"


def test_error_entry_raises_backend_error(pack: Pack) -> None:
    b = ReplayBackend([{"message": "hi", "error": "backend_timeout"}], pack)
    with pytest.raises(BackendError) as exc:
        b.answer(req(pack, "hi"))
    assert exc.value.code == "backend_timeout"


def test_raw_answers_pass_through(pack: Pack) -> None:
    b = ReplayBackend([{"message": "hi", "raw_answers": {"q_optout": "yes"}}], pack)
    assert b.answer(req(pack, "hi")).scores == {"q_optout": "yes"}


def test_missing_message_is_malformed(pack: Pack) -> None:
    b = ReplayBackend([], pack)
    with pytest.raises(BackendError) as exc:
        b.answer(req(pack, "unknown"))
    assert exc.value.code == "malformed_response"


def test_digest_mismatch_raises(pack: Pack) -> None:
    with pytest.raises(PackError, match="questions_digest"):
        ReplayBackend([], pack, questions_digest="0" * 64)


def test_digest_match_ok(pack: Pack) -> None:
    ReplayBackend([], pack, questions_digest=pack.questions_digest)


def test_from_file_with_header_and_blank_lines(pack: Pack, tmp_path: Path) -> None:
    p = tmp_path / "answers.jsonl"
    p.write_text(
        json.dumps({"questions_digest": pack.questions_digest})
        + "\n\n"
        + json.dumps({"message": "hi", "scores": {"q_optout": 0.1}})
        + "\n",
        encoding="utf-8",
    )
    assert ReplayBackend.from_file(p, pack).answer(req(pack, "hi")).scores == {"q_optout": 0.1}


def test_from_file_stale_header_raises(pack: Pack, tmp_path: Path) -> None:
    p = tmp_path / "answers.jsonl"
    p.write_text(json.dumps({"questions_digest": "f" * 64}) + "\n", encoding="utf-8")
    with pytest.raises(PackError):
        ReplayBackend.from_file(p, pack)


def test_from_conformance_filters_by_pack(pack: Pack, tmp_path: Path) -> None:
    p = tmp_path / "cases.json"
    p.write_text(
        json.dumps(
            {
                "version": 1,
                "packs": {"mini": "x.yaml"},
                "cases": [
                    {
                        "name": "a",
                        "pack": "mini",
                        "input": {"message": "hi"},
                        "backend": {"scores": {"q_optout": 0.7}},
                        "expected": {},
                    },
                    {
                        "name": "b",
                        "pack": "other",
                        "input": {"message": "hi"},
                        "backend": {"scores": {"q_x": 0.1}},
                        "expected": {},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    assert ReplayBackend.from_conformance(p, pack).answer(req(pack, "hi")).scores == {
        "q_optout": 0.7
    }


async def test_async_matches_sync(pack: Pack) -> None:
    b = ReplayBackend([{"message": "hi", "scores": {"q_optout": 0.4}}], pack)
    assert (await b.answer_async(req(pack, "hi"))) == b.answer(req(pack, "hi"))
    b.close()
    await b.aclose()
