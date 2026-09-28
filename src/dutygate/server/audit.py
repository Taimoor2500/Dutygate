from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from ..decision import Decision
from ..errors import ConfigError


class AuditLog:
    """Append-only JSONL audit trail. Message text is stored only when explicitly enabled."""

    def __init__(self, path: Path, *, include_message: bool = False) -> None:
        self.path = path
        self.include_message = include_message
        self._lock = asyncio.Lock()
        try:
            with path.open("a", encoding="utf-8"):
                pass
        except OSError as exc:
            raise ConfigError(f"cannot write the audit log {path}: {exc}") from None

    async def write(self, *, request_id: str, pack: str, decision: Decision, message: str) -> None:
        record: dict[str, object] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "request_id": request_id,
            "pack": pack,
            "decision": decision.to_dict(),
        }
        if self.include_message:
            record["message"] = message
        line = json.dumps(record, ensure_ascii=False) + "\n"
        async with self._lock:
            await asyncio.to_thread(self._append, line)

    def _append(self, line: str) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line)
