from __future__ import annotations

import dataclasses
from typing import Any

from .metrics import Metrics


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return lines


def render_markdown(
    metrics: Metrics,
    baseline: Metrics | None = None,
    *,
    name: str = "backend",
    baseline_name: str = "baseline",
) -> str:
    cols = [name] + ([baseline_name] if baseline else [])

    def both(attr: str) -> list[str]:
        vals = [_pct(getattr(metrics, attr))]
        if baseline:
            vals.append(_pct(getattr(baseline, attr)))
        return vals

    out = [f"Rows: {metrics.n_pos} positive, {metrics.n_neg} clean, {metrics.errors} errors", ""]
    out += _table(
        ["metric", *cols],
        [
            ["caught (routed or reviewed)", *both("caught_rate")],
            ["routed", *both("route_rate")],
            ["false review (clean not continued)", *both("false_review_rate")],
            ["route precision", *both("route_precision")],
        ],
    )

    out += ["", "Per category (recall / precision):", ""]
    cat_rows = []
    for cat, cm in metrics.per_category.items():
        row = [cat, str(cm.support), f"{_pct(cm.recall)} / {_pct(cm.precision)}"]
        if baseline:
            bm = baseline.per_category.get(cat)
            row.append(f"{_pct(bm.recall)} / {_pct(bm.precision)}" if bm else "n/a")
        cat_rows.append(row)
    out += _table(["category", "support", *cols], cat_rows)

    if metrics.per_tag:
        out += ["", "Per tag (caught on positives / false review on clean):", ""]
        tag_rows = []
        for tag, tm in metrics.per_tag.items():
            row = [
                tag,
                f"{tm.n_pos}/{tm.n_neg}",
                f"{_pct(tm.caught_rate)} / {_pct(tm.false_review_rate)}",
            ]
            if baseline:
                bt = baseline.per_tag.get(tag)
                row.append(
                    f"{_pct(bt.caught_rate)} / {_pct(bt.false_review_rate)}" if bt else "n/a"
                )
            tag_rows.append(row)
        out += _table(["tag", "pos/clean", *cols], tag_rows)
    return "\n".join(out) + "\n"


def to_json(metrics: Metrics, baseline: Metrics | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {"metrics": dataclasses.asdict(metrics)}
    if baseline is not None:
        data["baseline"] = dataclasses.asdict(baseline)
    return data
