from fractions import Fraction

import pytest

from dutygate.decision import Decision, Flag
from dutygate.evaluation.dataset import Row
from dutygate.evaluation.harness import RowResult
from dutygate.evaluation.metrics import check_fail_under, compute_metrics
from dutygate.evaluation.report import render_markdown, to_json

CATEGORIES = ("legal_threat", "privacy_request", "opt_out")


def flag(category: str, level: str) -> Flag:
    return Flag(category, category.replace("_", "-"), "q", "high", 0.5, level)  # type: ignore[arg-type]


def result(
    rid: str,
    labels: list[str],
    tags: list[str],
    action: str,
    flags: list[Flag],
    error: bool = False,
) -> RowResult:
    from dutygate.decision import ErrorInfo

    decision = Decision(
        id="dec_x",
        action=action,
        primary=flags[0].category if flags else None,  # type: ignore[arg-type]
        flags=tuple(flags),
        error=ErrorInfo("backend_timeout", "t") if error else None,
        policy={"name": "p", "version": "1.0.0"},
        backend={"name": "b", "model": None},
        conversation_id=None,
        latency_ms=10,
    )
    row = Row(
        id=rid, message=f"m {rid}", labels=tuple(labels), tags=tuple(tags), lang="en", channel=None
    )
    return RowResult(row=row, decision=decision, scores=None)


SIX = [
    result("r1", ["opt_out"], ["plain"], "route", [flag("opt_out", "confident")]),
    result(
        "r2",
        ["privacy_request", "opt_out"],
        ["multi-flag"],
        "review",
        [flag("privacy_request", "grey")],
    ),
    result("r3", ["legal_threat"], ["slang"], "continue", []),
    result("r4", [], ["near-miss"], "review", [flag("opt_out", "grey")]),
    result("r5", [], ["plain"], "continue", []),
    result("r6", [], ["plain"], "route", [flag("legal_threat", "confident")]),
]


def approx(x: Fraction) -> object:
    return pytest.approx(float(x))


def test_headline_metrics() -> None:
    m = compute_metrics(SIX, CATEGORIES)
    assert (m.n_pos, m.n_neg, m.errors) == (3, 3, 0)
    assert m.caught_rate == approx(Fraction(2, 3))
    assert m.route_rate == approx(Fraction(1, 3))
    assert m.false_review_rate == approx(Fraction(2, 3))
    assert m.route_precision == approx(Fraction(1, 2))


def test_per_category() -> None:
    m = compute_metrics(SIX, CATEGORIES)
    opt = m.per_category["opt_out"]
    assert (opt.support, opt.recall, opt.precision) == (2, 0.5, 0.5)
    priv = m.per_category["privacy_request"]
    assert (priv.support, priv.recall, priv.precision) == (1, 1.0, 1.0)
    legal = m.per_category["legal_threat"]
    assert (legal.support, legal.recall, legal.precision) == (1, 0.0, 0.0)


def test_per_tag() -> None:
    m = compute_metrics(SIX, CATEGORIES)
    plain = m.per_tag["plain"]
    assert (plain.n_pos, plain.n_neg, plain.caught_rate, plain.false_review_rate) == (
        1,
        2,
        1.0,
        0.5,
    )
    multi = m.per_tag["multi-flag"]
    assert (multi.caught_rate, multi.false_review_rate) == (1.0, None)
    assert m.per_tag["slang"].caught_rate == 0.0
    assert m.per_tag["near-miss"].false_review_rate == 1.0


def test_empty_denominators_are_none() -> None:
    m = compute_metrics([SIX[4]], CATEGORIES)
    assert m.caught_rate is None and m.route_rate is None and m.route_precision is None
    assert m.per_category["opt_out"].recall is None
    assert m.per_category["opt_out"].precision is None


def test_errors_counted() -> None:
    errored = result("r7", ["opt_out"], [], "review", [], error=True)
    m = compute_metrics([*SIX, errored], CATEGORIES)
    assert m.errors == 1
    assert m.caught_rate == approx(Fraction(3, 4))  # an error review still counts as caught


def test_fail_under() -> None:
    m = compute_metrics(SIX, CATEGORIES)
    assert check_fail_under(m, "caught=0.6") == []
    failures = check_fail_under(m, "caught=0.95, false_review=0.10")
    assert len(failures) == 2
    assert "caught" in failures[0] and "false_review" in failures[1]
    assert check_fail_under(m, "route_precision=0.5,route=0.3") == []


@pytest.mark.parametrize("spec", ["bogus=0.5", "caught", "caught=abc", "caught=1.5"])
def test_fail_under_bad_spec(spec: str) -> None:
    with pytest.raises(ValueError):
        check_fail_under(compute_metrics(SIX, CATEGORIES), spec)


def test_fail_under_missing_metric_fails() -> None:
    m = compute_metrics([SIX[4]], CATEGORIES)  # no positives: caught is None
    assert check_fail_under(m, "caught=0.9") != []


def test_markdown_and_json() -> None:
    m = compute_metrics(SIX, CATEGORIES)
    base = compute_metrics(SIX[:3], CATEGORIES)
    md = render_markdown(m, baseline=base, name="jev", baseline_name="keyword")
    assert "| caught" in md and "keyword" in md and "jev" in md
    assert "66.7%" in md
    assert "slang" in md and "opt_out" in md
    plain = render_markdown(m)
    assert "keyword" not in plain
    data = to_json(m, baseline=base)
    assert data["metrics"]["caught_rate"] == pytest.approx(2 / 3)
    assert data["baseline"]["n_pos"] == 3
    assert data["metrics"]["per_category"]["opt_out"]["recall"] == 0.5
