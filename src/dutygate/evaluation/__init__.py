"""Evaluation harness: score any backend on a labeled dataset, replay saved answers, sweep."""

from .dataset import Row, load_dataset
from .harness import RowResult, run, run_async
from .metrics import Metrics, check_fail_under, compute_metrics
from .report import render_markdown, to_json

__all__ = [
    "Metrics",
    "Row",
    "RowResult",
    "check_fail_under",
    "compute_metrics",
    "load_dataset",
    "render_markdown",
    "run",
    "run_async",
    "to_json",
]
