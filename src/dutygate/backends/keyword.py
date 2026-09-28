"""Keyword-regex backend. An evaluation baseline only: never use it as a production fallback."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path

import yaml

from ..errors import PackError
from ..schema import Pack
from .base import BackendRequest, BackendResult, SyncBackendBase


class KeywordBackend(SyncBackendBase):
    name = "keyword"

    def __init__(self, keywords: Mapping[str, Sequence[str]], pack: Pack) -> None:
        known = {q.id for q in pack.questions}
        errors: list[str] = []
        compiled: dict[str, list[re.Pattern[str]]] = {}
        for qid, patterns in keywords.items():
            if qid not in known:
                errors.append(f"keywords: unknown question id '{qid}'")
                continue
            if isinstance(patterns, (str, bytes)) or not isinstance(patterns, Sequence):
                errors.append(f"keywords.{qid}: must be a list of regex strings")
                continue
            compiled[qid] = []
            for p in patterns:
                if not isinstance(p, str):
                    errors.append(
                        f"keywords.{qid}: pattern {p!r} is not a string (quote it in YAML)"
                    )
                    continue
                try:
                    compiled[qid].append(re.compile(p, re.IGNORECASE))
                except re.error as exc:
                    errors.append(f"keywords.{qid}: invalid regex {p!r}: {exc}")
        if errors:
            raise PackError(errors)
        self._pack = pack
        self._patterns = compiled

    @classmethod
    def from_file(cls, path: str | Path, pack: Pack) -> KeywordBackend:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise PackError([f"{path}: keywords file must map question ids to regex lists"])
        return cls(data, pack)

    def answer(self, req: BackendRequest) -> BackendResult:
        text = str(req.state.get(self._pack.state_field, ""))
        scores = {
            q.id: 1.0 if any(p.search(text) for p in self._patterns.get(q.id, ())) else 0.0
            for q in req.questions
        }
        return BackendResult(scores=scores, model=self.name)
