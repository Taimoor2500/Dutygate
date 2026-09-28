from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ..schema import Question


@dataclass(frozen=True)
class BackendRequest:
    state: dict[str, Any]
    questions: tuple[Question, ...]


@dataclass(frozen=True)
class BackendResult:
    """Raw per-question scores. The engine validates them; backends need not."""

    scores: dict[str, Any]
    model: str | None = None


@runtime_checkable
class Backend(Protocol):
    name: str

    def answer(self, req: BackendRequest) -> BackendResult: ...

    async def answer_async(self, req: BackendRequest) -> BackendResult: ...

    def close(self) -> None: ...

    async def aclose(self) -> None: ...


class SyncBackendBase:
    """For backends that never do I/O: async delegates to sync, closing is a no-op."""

    name: str = "sync"

    def answer(self, req: BackendRequest) -> BackendResult:  # pragma: no cover - abstract
        raise NotImplementedError

    async def answer_async(self, req: BackendRequest) -> BackendResult:
        return self.answer(req)

    def close(self) -> None:
        return None

    async def aclose(self) -> None:
        return None
