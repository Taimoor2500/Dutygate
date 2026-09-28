from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .harness import RowResult


def _rate(num: int, den: int) -> float | None:
    return num / den if den else None


@dataclass(frozen=True)
class CategoryMetrics:
    support: int  # rows labeled with this category
    recall: float | None  # labeled rows whose flags include the category (any level)
    precision: float | None  # flagged rows that carry the label


@dataclass(frozen=True)
class TagMetrics:
    n_pos: int
    n_neg: int
    caught_rate: float | None
    false_review_rate: float | None


@dataclass(frozen=True)
class Metrics:
    n_pos: int
    n_neg: int
    caught_rate: float | None  # positives whose action != continue
    route_rate: float | None  # positives routed
    false_review_rate: float | None  # clean rows whose action != continue
    route_precision: float | None  # routed rows that are positive
    errors: int
    per_category: dict[str, CategoryMetrics] = field(default_factory=dict)
    per_tag: dict[str, TagMetrics] = field(default_factory=dict)


def _flagged(result: RowResult) -> set[str]:
    return {f.category for f in result.decision.flags}


def compute_metrics(results: Sequence[RowResult], categories: Sequence[str]) -> Metrics:
    pos = [r for r in results if r.row.positive]
    neg = [r for r in results if not r.row.positive]
    caught = sum(r.decision.action != "continue" for r in pos)
    routed_pos = sum(r.decision.action == "route" for r in pos)
    false_reviews = sum(r.decision.action != "continue" for r in neg)
    routed = [r for r in results if r.decision.action == "route"]

    per_category = {}
    for cat in categories:
        labeled = [r for r in results if cat in r.row.labels]
        flagged = [r for r in results if cat in _flagged(r)]
        per_category[cat] = CategoryMetrics(
            support=len(labeled),
            recall=_rate(sum(cat in _flagged(r) for r in labeled), len(labeled)),
            precision=_rate(sum(cat in r.row.labels for r in flagged), len(flagged)),
        )

    per_tag = {}
    for tag in sorted({t for r in results for t in r.row.tags}):
        tp = [r for r in pos if tag in r.row.tags]
        tn = [r for r in neg if tag in r.row.tags]
        per_tag[tag] = TagMetrics(
            n_pos=len(tp),
            n_neg=len(tn),
            caught_rate=_rate(sum(r.decision.action != "continue" for r in tp), len(tp)),
            false_review_rate=_rate(sum(r.decision.action != "continue" for r in tn), len(tn)),
        )

    return Metrics(
        n_pos=len(pos),
        n_neg=len(neg),
        caught_rate=_rate(caught, len(pos)),
        route_rate=_rate(routed_pos, len(pos)),
        false_review_rate=_rate(false_reviews, len(neg)),
        route_precision=_rate(sum(r.row.positive for r in routed), len(routed)),
        errors=sum(r.decision.error is not None for r in results),
        per_category=per_category,
        per_tag=per_tag,
    )


# metric name in --fail-under -> (attribute, higher_is_better)
TARGETS: dict[str, tuple[str, bool]] = {
    "caught": ("caught_rate", True),
    "route": ("route_rate", True),
    "false_review": ("false_review_rate", False),
    "route_precision": ("route_precision", True),
}


def check_fail_under(metrics: Metrics, spec: str) -> list[str]:
    """Parse "caught=0.95,false_review=0.10" and return one message per missed target.

    Raises ValueError for an unknown metric or a malformed threshold.
    """
    failures = []
    for part in (p.strip() for p in spec.split(",")):
        if not part:
            continue
        name, sep, raw = part.partition("=")
        name = name.strip()
        if not sep or name not in TARGETS:
            known = ", ".join(TARGETS)
            raise ValueError(
                f"bad --fail-under entry {part!r}; use name=value with name in {known}"
            )
        try:
            target = float(raw)
        except ValueError:
            raise ValueError(f"bad --fail-under value in {part!r}") from None
        if not 0.0 <= target <= 1.0:
            raise ValueError(f"--fail-under value must be between 0 and 1 in {part!r}")
        attr, higher_is_better = TARGETS[name]
        value: float | None = getattr(metrics, attr)
        if value is None:
            failures.append(f"{name}: no data to measure (target {target:.2f})")
        elif higher_is_better and value < target:
            failures.append(f"{name}: {value:.3f} is below the target {target:.2f}")
        elif not higher_is_better and value > target:
            failures.append(f"{name}: {value:.3f} is above the limit {target:.2f}")
    return failures
