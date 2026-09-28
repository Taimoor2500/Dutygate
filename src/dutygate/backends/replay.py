"""Deterministic backend that answers from saved fixtures (tests, conformance, eval replay)."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..errors import BackendError, ErrorCode, PackError
from ..redact import Redactor
from ..schema import Pack
from .base import BackendRequest, BackendResult, SyncBackendBase


class ReplayBackend(SyncBackendBase):
    """Looks answers up by the redacted message the engine sends.

    Each entry is ``{"message": raw_text}`` plus exactly one of ``scores`` (question id -> value),
    ``error`` (an engine error code to raise) or ``raw_answers`` (passed through unvalidated, to
    replay malformed responses).
    """

    name = "replay"

    def __init__(
        self,
        entries: Iterable[dict[str, Any]],
        pack: Pack,
        *,
        questions_digest: str | None = None,
    ) -> None:
        if questions_digest is not None and questions_digest != pack.questions_digest:
            raise PackError(
                [
                    "replay fixtures were recorded against different questions "
                    f"(questions_digest {questions_digest[:12]}… != "
                    f"pack {pack.questions_digest[:12]}…); re-record them"
                ]
            )
        self._pack = pack
        redactor = Redactor(pack.redaction)
        self._table: dict[str, dict[str, Any]] = {}
        for entry in entries:
            if "message" not in entry:
                raise PackError([f"replay entry without 'message': {entry!r}"])
            self._table[redactor.redact(str(entry["message"]))] = entry

    @classmethod
    def from_file(cls, path: str | Path, pack: Pack) -> ReplayBackend:
        digest: str | None = None
        entries: list[dict[str, Any]] = []
        for lineno, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise PackError([f"{path}:{lineno}: invalid JSON: {exc}"]) from exc
            if "questions_digest" in obj and "message" not in obj:
                digest = obj["questions_digest"]
            else:
                entries.append(obj)
        return cls(entries, pack, questions_digest=digest)

    @classmethod
    def from_conformance(cls, path: str | Path, pack: Pack) -> ReplayBackend:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        entries = []
        for case in doc["cases"]:
            if case.get("pack", "legal-triggers") != pack.name:
                continue
            entries.append({"message": case["input"]["message"], **case["backend"]})
        return cls(entries, pack)

    def answer(self, req: BackendRequest) -> BackendResult:
        message = str(req.state.get(self._pack.state_field, ""))
        entry = self._table.get(message)
        if entry is None:
            raise BackendError("malformed_response", "no replay fixture for this message")
        if "error" in entry:
            code: ErrorCode = entry["error"]
            raise BackendError(code, f"replayed {code}")
        if "raw_answers" in entry:
            return BackendResult(scores=dict(entry["raw_answers"]), model=self.name)
        return BackendResult(scores=dict(entry["scores"]), model=self.name)
