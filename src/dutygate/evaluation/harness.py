from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..backends.base import Backend, BackendRequest, BackendResult
from ..decision import Decision
from ..engine import evaluate_async
from ..errors import BackendError
from ..redact import Redactor
from ..schema import Pack
from .dataset import Row


@dataclass(frozen=True)
class RowResult:
    row: Row
    decision: Decision
    scores: dict[str, Any] | None  # raw backend answers; None if the backend was not reached


class _Recorder:
    """Wraps a backend for one row and keeps what it answered."""

    def __init__(self, inner: Backend) -> None:
        self.inner = inner
        self.name = inner.name
        self.result: BackendResult | None = None
        self.error: str | None = None

    def answer(self, req: BackendRequest) -> BackendResult:  # pragma: no cover - async only
        raise NotImplementedError

    async def answer_async(self, req: BackendRequest) -> BackendResult:
        try:
            self.result = await self.inner.answer_async(req)
        except BackendError as exc:
            self.error = exc.code
            raise
        return self.result

    def close(self) -> None:  # pragma: no cover - the harness closes the inner backend
        return None

    async def aclose(self) -> None:  # pragma: no cover
        return None


async def run_async(
    pack: Pack,
    rows: Sequence[Row],
    backend: Backend,
    *,
    concurrency: int = 4,
    save_answers: Path | None = None,
) -> list[RowResult]:
    semaphore = asyncio.Semaphore(max(1, concurrency))
    redactor = Redactor(pack.redaction)

    async def one(row: Row) -> tuple[RowResult, _Recorder]:
        recorder = _Recorder(backend)
        async with semaphore:
            decision = await evaluate_async(
                pack, row.message, recorder, channel=row.channel, redactor=redactor
            )
        scores = dict(recorder.result.scores) if recorder.result else None
        return RowResult(row=row, decision=decision, scores=scores), recorder

    outcomes = await asyncio.gather(*(one(r) for r in rows))
    if save_answers is not None:
        _write_answers(save_answers, pack, outcomes)
    return [result for result, _ in outcomes]


def run(
    pack: Pack,
    rows: Sequence[Row],
    backend: Backend,
    *,
    concurrency: int = 4,
    save_answers: Path | None = None,
) -> list[RowResult]:
    """Evaluate every row (concurrently, bounded) and return results in dataset order."""
    return asyncio.run(
        run_async(pack, rows, backend, concurrency=concurrency, save_answers=save_answers)
    )


def _write_answers(path: Path, pack: Pack, outcomes: Sequence[tuple[RowResult, _Recorder]]) -> None:
    lines = [json.dumps({"questions_digest": pack.questions_digest})]
    written: set[str] = set()
    for result, recorder in outcomes:
        message = result.row.message
        if message in written:
            continue
        entry: dict[str, Any] | None = None
        if recorder.result is not None:
            entry = {"message": message, "scores": recorder.result.scores}
        elif recorder.error is not None:
            entry = {"message": message, "error": recorder.error}
        if entry is not None:
            written.add(message)
            lines.append(json.dumps(entry, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
