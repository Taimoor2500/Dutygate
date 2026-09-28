import json
from pathlib import Path

import pytest

from dutygate.errors import PackError
from dutygate.evaluation.dataset import Row
from dutygate.evaluation.sweep import best_point, load_answers, pareto, sweep

from ..helpers import make_pack, zeros


def row(rid: str, labels: tuple[str, ...]) -> Row:
    return Row(id=rid, message=f"m{rid}", labels=labels, tags=(), lang="en", channel=None)


# cat_a positives score 0.3 and 0.6; clean rows score 0.1 and 0.35 on q_a.
ROWS = [row("1", ("cat_a",)), row("2", ("cat_a",)), row("3", ()), row("4", ())]
ANSWERS = {
    "m1": zeros(q_a=0.3),
    "m2": zeros(q_a=0.6),
    "m3": zeros(q_a=0.1),
    "m4": zeros(q_a=0.35),
}
GRID = (0.1, 0.2, 0.3, 0.4, 0.5)


def test_sweep_covers_grid_for_each_rule() -> None:
    points = sweep(make_pack(), ROWS, ANSWERS, grid=GRID)
    rule_a = [p for p in points if p.rule_id == "rule-a"]
    assert len(rule_a) == 15  # pairs with low <= high
    assert {p.rule_id for p in points} == {"rule-a", "rule-b", "rule-c"}


def test_sweep_values() -> None:
    points = {
        (p.low, p.high): p
        for p in sweep(make_pack(), ROWS, ANSWERS, grid=GRID)
        if p.rule_id == "rule-a"
    }
    p = points[(0.3, 0.5)]
    assert (p.recall, p.route_recall, p.false_review) == (1.0, 0.5, 0.5)
    p = points[(0.4, 0.5)]
    assert (p.recall, p.false_review) == (0.5, 0.0)
    p = points[(0.1, 0.1)]
    assert (p.recall, p.route_recall, p.false_review) == (1.0, 1.0, 1.0)


def test_best_point_for_target_recall() -> None:
    points = sweep(make_pack(), ROWS, ANSWERS, grid=GRID)
    best = best_point(points, "rule-a", min_recall=1.0)
    assert best is not None
    # recall 1.0 needs low <= 0.3; false review is then 0.5 at best (m4=0.35 is unavoidable)
    assert (best.low, best.false_review) == (0.3, 0.5)
    assert best_point(points, "rule-a", min_recall=1.01) is None


def test_pareto_is_non_dominated() -> None:
    front = pareto(
        [p for p in sweep(make_pack(), ROWS, ANSWERS, grid=GRID) if p.rule_id == "rule-a"]
    )
    for p in front:
        assert not any(q.recall >= p.recall and q.false_review < p.false_review for q in front)


def test_sweep_makes_no_backend_calls_and_skips_unanswered_rows() -> None:
    rows = [*ROWS, row("5", ("cat_a",))]  # m5 has no saved answer
    points = sweep(make_pack(), rows, ANSWERS, grid=(0.3,))
    assert points[0].n_rows == 4


def test_load_answers(tmp_path: Path) -> None:
    pack = make_pack()
    p = tmp_path / "a.jsonl"
    p.write_text(
        json.dumps({"questions_digest": pack.questions_digest})
        + "\n"
        + json.dumps({"message": "m1", "scores": zeros(q_a=0.3)})
        + "\n"
        + json.dumps({"message": "m2", "error": "backend_timeout"})
        + "\n",
        encoding="utf-8",
    )
    assert load_answers(p, pack) == {"m1": zeros(q_a=0.3)}


def test_load_answers_stale(tmp_path: Path) -> None:
    p = tmp_path / "a.jsonl"
    p.write_text(json.dumps({"questions_digest": "0" * 64}) + "\n", encoding="utf-8")
    with pytest.raises(PackError):
        load_answers(p, make_pack())
