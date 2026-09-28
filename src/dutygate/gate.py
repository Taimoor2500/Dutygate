from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from types import TracebackType

from .backends.base import Backend
from .decision import Decision
from .engine import evaluate, evaluate_async
from .redact import Redactor
from .schema import Pack, load_policy

logger = logging.getLogger("dutygate")


class Gate:
    """A pack bound to a backend: the object hosts call before every bot reply."""

    def __init__(
        self,
        pack: Pack,
        backend: Backend,
        *,
        on_decision: Callable[[Decision], None] | None = None,
    ) -> None:
        self.pack = pack
        self.backend = backend
        self._on_decision = on_decision
        self._redactor = Redactor(pack.redaction)

    @classmethod
    def from_pack(
        cls,
        path: str | Path,
        backend: Backend | None = None,
        *,
        on_decision: Callable[[Decision], None] | None = None,
    ) -> Gate:
        pack = load_policy(path)
        if backend is None:
            from .backends.jev import TypeSafeJevBackend

            backend = TypeSafeJevBackend.from_env()
        return cls(pack, backend, on_decision=on_decision)

    def _notify(self, decision: Decision) -> Decision:
        if self._on_decision is not None:
            try:
                self._on_decision(decision)
            except Exception:
                logger.exception("on_decision hook failed", extra={"pack": self.pack.name})
        return decision

    def check(
        self,
        message: str,
        *,
        conversation_id: str | None = None,
        channel: str | None = None,
        recent_messages: Sequence[str] | None = None,
    ) -> Decision:
        return self._notify(
            evaluate(
                self.pack,
                message,
                self.backend,
                conversation_id=conversation_id,
                channel=channel,
                recent_messages=recent_messages,
                redactor=self._redactor,
            )
        )

    async def check_async(
        self,
        message: str,
        *,
        conversation_id: str | None = None,
        channel: str | None = None,
        recent_messages: Sequence[str] | None = None,
    ) -> Decision:
        return self._notify(
            await evaluate_async(
                self.pack,
                message,
                self.backend,
                conversation_id=conversation_id,
                channel=channel,
                recent_messages=recent_messages,
                redactor=self._redactor,
            )
        )

    def close(self) -> None:
        self.backend.close()

    async def aclose(self) -> None:
        await self.backend.aclose()

    def __enter__(self) -> Gate:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    async def __aenter__(self) -> Gate:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()
