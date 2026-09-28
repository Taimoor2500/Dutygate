from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..errors import DatasetError


@dataclass(frozen=True)
class Row:
    id: str
    message: str
    labels: tuple[str, ...]
    tags: tuple[str, ...]
    lang: str
    channel: str | None

    @property
    def positive(self) -> bool:
        return bool(self.labels)


def _str_list(obj: dict[str, Any], key: str, where: str) -> tuple[str, ...]:
    value = obj.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise DatasetError(f"{where}: '{key}' must be a list of strings")
    return tuple(value)


def load_dataset(path: str | Path) -> list[Row]:
    """Read a JSONL dataset: one {"id", "message", "labels", "tags", "lang", "channel"} per line."""
    rows: list[Row] = []
    seen: set[str] = set()
    for lineno, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        where = f"{path}:{lineno}"
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DatasetError(f"{where}: invalid JSON: {exc}") from None
        if not isinstance(obj, dict):
            raise DatasetError(f"{where}: each line must be a JSON object")
        rid = obj.get("id")
        if not isinstance(rid, str) or not rid:
            raise DatasetError(f"{where}: missing string 'id'")
        if rid in seen:
            raise DatasetError(f"{where}: duplicate id '{rid}'")
        seen.add(rid)
        message = obj.get("message")
        if not isinstance(message, str) or not message.strip():
            raise DatasetError(f"{where}: empty message for id '{rid}'")
        channel = obj.get("channel")
        if channel is not None and not isinstance(channel, str):
            raise DatasetError(f"{where}: 'channel' must be a string")
        rows.append(
            Row(
                id=rid,
                message=message,
                labels=_str_list(obj, "labels", where),
                tags=_str_list(obj, "tags", where),
                lang=str(obj.get("lang", "en")),
                channel=channel,
            )
        )
    return rows
