"""Threshold sweep over saved answers: no backend calls, so tuning is free."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..engine import decide, validate_scores
from ..errors import BackendError, PackError
from ..schema import Pack, Thresholds
from .dataset import Row

DEFAULT_GRID: tuple[float, ...] = tuple(round(0.05 * i, 2) for i in range(1, 19))  # 0.05..0.90


@dataclass(frozen=True)
class SweepPoint:
    rule_id: str
    low: float
    high: float
    recall: float  # rows labeled with the rule's category whose flags include it
    route_recall: float  # ... flagged at the confident level
    false_review: float  # clean rows whose action is not continue (all rules applied)
    n_rows: int


def load_answers(path: str | Path, pack: Pack) -> dict[str, dict[str, float]]:
    """Read a --save-answers file into {raw message: validated scores}; error rows are skipped."""
    out: dict[str, dict[str, float]] = {}
    for lineno, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PackError([f"{path}:{lineno}: invalid JSON: {exc}"]) from None
        if "questions_digest" in obj and "message" not in obj:
            if obj["questions_digest"] != pack.questions_digest:
                raise PackError(
                    [f"{path}: answers were recorded against different questions; re-record them"]
                )
        elif "scores" in obj and "message" in obj:
            try:
                out[obj["message"]] = validate_scores(pack, obj["scores"])
            except BackendError:
                continue
    return out


def _with_thresholds(pack: Pack, rule_id: str, low: float, high: float) -> Pack:
    rules = tuple(
        r.model_copy(update={"thresholds": Thresholds(low=low, high=high)})
        if r.id == rule_id
        else r
        for r in pack.rules
    )
    return pack.model_copy(update={"rules": rules})


def sweep(
    pack: Pack,
    rows: Sequence[Row],
    answers: Mapping[str, Mapping[str, float]],
    *,
    grid: Sequence[float] = DEFAULT_GRID,
) -> list[SweepPoint]:
    scored = [(r, answers[r.message]) for r in rows if r.message in answers]
    clean = [(r, s) for r, s in scored if not r.positive]
    points = []
    for rule in pack.rules:
        labeled = [(r, s) for r, s in scored if rule.category in r.labels]
        for low in grid:
            for high in grid:
                if low > high:
                    continue
                trial = _with_thresholds(pack, rule.id, low, high)
                hits = routed = 0
                for _, s in labeled:
                    _, _, flags = decide(trial, s)
                    levels = {f.level for f in flags if f.category == rule.category}
                    hits += bool(levels)
                    routed += "confident" in levels
                false = sum(decide(trial, s)[0] != "continue" for _, s in clean)
                points.append(
                    SweepPoint(
                        rule_id=rule.id,
                        low=low,
                        high=high,
                        recall=hits / len(labeled) if labeled else 0.0,
                        route_recall=routed / len(labeled) if labeled else 0.0,
                        false_review=false / len(clean) if clean else 0.0,
                        n_rows=len(scored),
                    )
                )
    return points


def best_point(
    points: Sequence[SweepPoint], rule_id: str, *, min_recall: float
) -> SweepPoint | None:
    """Lowest false-review point reaching min_recall; ties prefer the stricter thresholds."""
    ok = [p for p in points if p.rule_id == rule_id and p.recall >= min_recall]
    if not ok:
        return None
    return min(ok, key=lambda p: (p.false_review, -p.route_recall, -p.low, -p.high))


def pareto(points: Sequence[SweepPoint]) -> list[SweepPoint]:
    """Points not beaten on both recall (higher) and false review (lower), best recall first."""
    front: list[SweepPoint] = []
    for p in sorted(points, key=lambda p: (-p.recall, p.false_review, -p.route_recall, -p.low)):
        if not front or p.false_review < front[-1].false_review:
            front.append(p)
    return front
