import json
from pathlib import Path

import pytest

from dutygate import KeywordBackend, ReplayBackend
from dutygate.errors import DatasetError
from dutygate.evaluation.dataset import load_dataset
from dutygate.evaluation.harness import run

from ..helpers import StaticBackend, make_pack, zeros


def write_rows(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    p = tmp_path / "ds.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n\n", encoding="utf-8")
    return p


ROWS: list[dict[str, object]] = [
    {"id": "a", "message": "alpha please", "labels": ["cat_a"], "tags": ["plain"], "lang": "en"},
    {"id": "b", "message": "nothing here", "labels": [], "tags": ["near-miss"], "lang": "en"},
    {
        "id": "c",
        "message": "charlie",
        "labels": ["cat_c"],
        "tags": [],
        "lang": "fr",
        "channel": "sms",
    },
]


def test_load_dataset(tmp_path: Path) -> None:
    rows = load_dataset(write_rows(tmp_path, ROWS))
    assert [r.id for r in rows] == ["a", "b", "c"]
    assert rows[0].labels == ("cat_a",) and rows[1].labels == ()
    assert rows[2].channel == "sms" and rows[2].lang == "fr"


def test_load_dataset_defaults(tmp_path: Path) -> None:
    rows = load_dataset(write_rows(tmp_path, [{"id": "x", "message": "hi"}]))
    assert (rows[0].labels, rows[0].tags, rows[0].lang) == ((), (), "en")


@pytest.mark.parametrize(
    ("rows", "needle"),
    [
        ([{"id": "a", "message": "x"}, {"id": "a", "message": "y"}], "duplicate id 'a'"),
        ([{"id": "a", "message": "   "}], "empty message"),
        ([{"message": "no id"}], "id"),
        ([{"id": "a", "message": "x", "labels": "opt_out"}], "labels"),
    ],
)
def test_load_dataset_errors(tmp_path: Path, rows: list[dict[str, object]], needle: str) -> None:
    with pytest.raises(DatasetError, match=needle):
        load_dataset(write_rows(tmp_path, rows))


def test_load_dataset_bad_json(tmp_path: Path) -> None:
    p = tmp_path / "ds.jsonl"
    p.write_text('{"id": "a", "message": "x"}\n{oops\n', encoding="utf-8")
    with pytest.raises(DatasetError, match=":2"):
        load_dataset(p)


def test_run_keyword_backend(tmp_path: Path) -> None:
    pack = make_pack()
    rows = load_dataset(write_rows(tmp_path, ROWS))
    backend = KeywordBackend({"q_a": ["alpha"], "q_c": ["charlie"]}, pack)
    results = run(pack, rows, backend, concurrency=2)
    assert [r.row.id for r in results] == ["a", "b", "c"]
    assert [r.decision.action for r in results] == ["route", "continue", "route"]
    assert results[0].scores == {"q_a": 1.0, "q_b": 0.0, "q_c": 0.0, "q_d": 0.0}


def test_run_passes_channel(tmp_path: Path) -> None:
    pack = make_pack()
    backend = StaticBackend(zeros())
    run(pack, load_dataset(write_rows(tmp_path, ROWS)), backend)
    assert {"customer_message": "charlie", "channel": "sms"} in [r.state for r in backend.requests]


def test_save_answers_round_trips(tmp_path: Path) -> None:
    pack = make_pack()
    rows = load_dataset(write_rows(tmp_path, ROWS))
    answers = tmp_path / "answers.jsonl"
    first = run(pack, rows, KeywordBackend({"q_a": ["alpha"]}, pack), save_answers=answers)
    header = json.loads(answers.read_text().splitlines()[0])
    assert header == {"questions_digest": pack.questions_digest}
    replayed = run(pack, rows, ReplayBackend.from_file(answers, pack))
    assert [r.decision.action for r in replayed] == [r.decision.action for r in first]
    assert [r.decision.flags for r in replayed] == [r.decision.flags for r in first]


def test_save_answers_records_errors(tmp_path: Path) -> None:
    from dutygate.errors import BackendError

    pack = make_pack()
    rows = load_dataset(write_rows(tmp_path, ROWS[:1]))
    answers = tmp_path / "answers.jsonl"
    res = run(
        pack, rows, StaticBackend(exc=BackendError("backend_timeout", "slow")), save_answers=answers
    )
    assert res[0].decision.error is not None and res[0].scores is None
    lines = [json.loads(x) for x in answers.read_text().splitlines()]
    assert lines[1] == {"message": "alpha please", "error": "backend_timeout"}
