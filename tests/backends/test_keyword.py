from pathlib import Path

import pytest

from dutygate.backends.base import BackendRequest
from dutygate.backends.keyword import KeywordBackend
from dutygate.errors import PackError
from dutygate.schema import Pack, load_policy

from .test_replay import PACK


@pytest.fixture
def pack() -> Pack:
    return load_policy(PACK)


def req(pack: Pack, message: str) -> BackendRequest:
    return BackendRequest(state={"customer_message": message}, questions=pack.questions)


def test_case_insensitive_match(pack: Pack) -> None:
    b = KeywordBackend({"q_optout": [r"\bstop\b", "unsubscribe"]}, pack)
    assert b.answer(req(pack, "Please STOP texting")).scores == {"q_optout": 1.0}
    assert b.answer(req(pack, "the app keeps stopping")).scores == {"q_optout": 0.0}
    assert b.answer(req(pack, "anything")).model == "keyword"


def test_question_without_keywords_scores_zero(pack: Pack) -> None:
    assert KeywordBackend({}, pack).answer(req(pack, "stop")).scores == {"q_optout": 0.0}


def test_unknown_question_id_rejected(pack: Pack) -> None:
    with pytest.raises(PackError, match="q_nope"):
        KeywordBackend({"q_nope": ["x"]}, pack)


def test_bad_regex_rejected(pack: Pack) -> None:
    with pytest.raises(PackError, match="q_optout"):
        KeywordBackend({"q_optout": ["(unclosed"]}, pack)


def test_from_file(pack: Pack, tmp_path: Path) -> None:
    p = tmp_path / "kw.yaml"
    p.write_text("q_optout:\n  - unsubscribe\n", encoding="utf-8")
    b = KeywordBackend.from_file(p, pack)
    assert b.answer(req(pack, "Unsubscribe me")).scores == {"q_optout": 1.0}


async def test_async(pack: Pack) -> None:
    b = KeywordBackend({"q_optout": ["stop"]}, pack)
    assert (await b.answer_async(req(pack, "stop"))).scores == {"q_optout": 1.0}


def test_non_string_pattern_rejected(pack: Pack, tmp_path: Path) -> None:
    p = tmp_path / "kw.yaml"
    p.write_text("q_optout: [yes, 12]\n", encoding="utf-8")  # YAML: True, 12
    with pytest.raises(PackError, match="q_optout"):
        KeywordBackend.from_file(p, pack)


def test_non_list_patterns_rejected(pack: Pack) -> None:
    with pytest.raises(PackError, match="q_optout"):
        KeywordBackend({"q_optout": "stop"}, pack)
