"""TypeSafe Jev backend: POST /v1/systemone with one noul question per pack question.

API reference: https://docs.typesafe.ai/api
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from .._version import __version__
from ..errors import BackendError, ConfigError
from ..schema import Question
from .base import BackendRequest, BackendResult

DEFAULT_BASE_URL = "https://api.typesafe.ai"
DEFAULT_MODEL = "jev-latest"
RETRYABLE_STATUS = frozenset({429, 529})


@dataclass(frozen=True)
class JevConfig:
    api_key: str = field(repr=False)
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout_ms: int = 5000
    max_retries: int = 1

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> JevConfig:
        env = os.environ if env is None else env
        key = env.get("TYPESAFE_API_KEY", "").strip()
        if not key:
            raise ConfigError("TYPESAFE_API_KEY is not set (needed for the jev backend)")
        base_url = env.get("TYPESAFE_BASE_URL", DEFAULT_BASE_URL).strip()
        if urlparse(base_url).scheme not in ("http", "https"):
            raise ConfigError(f"TYPESAFE_BASE_URL must be an http(s) URL, got {base_url!r}")
        return cls(
            api_key=key,
            base_url=base_url,
            model=env.get("DUTYGATE_JEV_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
            timeout_ms=_int_env(env, "DUTYGATE_TIMEOUT_MS", 5000, minimum=1),
            max_retries=_int_env(env, "DUTYGATE_MAX_RETRIES", 1, minimum=0),
        )


def _int_env(env: Mapping[str, str], name: str, default: int, *, minimum: int) -> int:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from None
    if value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got {value}")
    return value


def parse_response(body: Any, questions: tuple[Question, ...]) -> BackendResult:
    if not isinstance(body, dict) or not isinstance(body.get("answers"), dict):
        raise BackendError("malformed_response", "response has no 'answers' object")
    answers = body["answers"]
    scores: dict[str, Any] = {}
    for q in questions:
        ans = answers.get(q.id)
        if not isinstance(ans, dict):
            raise BackendError("malformed_response", f"no answer for question '{q.id}'")
        if ans.get("type") != "noul":
            raise BackendError("malformed_response", f"answer for '{q.id}' is not a noul")
        value = ans.get("noul")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise BackendError("malformed_response", f"answer for '{q.id}' has no numeric noul")
        scores[q.id] = value
    model = body.get("model")
    return BackendResult(scores=scores, model=model if isinstance(model, str) else None)


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


class _Attempts:
    """Retry and deadline bookkeeping shared by the sync and async request loops."""

    def __init__(self, config: JevConfig) -> None:
        self.config = config
        self.deadline = time.monotonic() + config.timeout_ms / 1000
        self.attempt = 0
        self.last_was_timeout = False

    def remaining(self) -> float:
        return self.deadline - time.monotonic()

    def timeout_error(self) -> BackendError:
        return BackendError("backend_timeout", f"no answer within {self.config.timeout_ms} ms")

    def handle(
        self, response: httpx.Response, content: bytes, questions: tuple[Question, ...]
    ) -> BackendResult | float:
        """Return a result, or the delay before retrying. Raises for final failures."""
        status = response.status_code
        if 200 <= status < 300:
            try:
                body = json.loads(content)
            except ValueError:
                raise BackendError("malformed_response", "response is not valid JSON") from None
            return parse_response(body, questions)
        if status in (401, 403):
            raise BackendError("backend_auth", f"TypeSafe rejected the API key (HTTP {status})")
        if status in RETRYABLE_STATUS or status >= 500:
            self.last_was_timeout = False
            return self.next_delay(_retry_after(response), f"HTTP {status}")
        raise BackendError("backend_rejected", f"TypeSafe rejected the request (HTTP {status})")

    def transport_failure(self, exc: Exception) -> float:
        self.last_was_timeout = isinstance(exc, (httpx.TimeoutException, TimeoutError))
        if self.remaining() <= 0:
            raise self.timeout_error()
        return self.next_delay(None, type(exc).__name__)

    def next_delay(self, retry_after: float | None, reason: str) -> float:
        if self.attempt >= self.config.max_retries:
            if self.last_was_timeout:
                raise self.timeout_error()
            raise BackendError(
                "backend_unavailable",
                f"TypeSafe unavailable after {self.attempt + 1} attempt(s) ({reason})",
            )
        remaining = self.remaining()
        if retry_after is not None:
            if retry_after >= remaining:
                raise BackendError(
                    "backend_unavailable",
                    f"TypeSafe asked to retry after {retry_after:g}s, "
                    f"beyond the time budget ({reason})",
                )
            delay = retry_after
        else:
            delay = min(0.2 * 2**self.attempt, max(remaining, 0.0)) * random.uniform(0.5, 1.0)
        self.attempt += 1
        return delay


class TypeSafeJevBackend:
    name = "typesafe-jev"

    def __init__(
        self,
        config: JevConfig,
        *,
        client: httpx.Client | None = None,
        async_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        self._url = config.base_url.rstrip("/") + "/v1/systemone"
        self._headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            "User-Agent": f"dutygate/{__version__}",
        }
        self._client = client
        self._owns_client = client is None
        self._async_client = async_client
        self._owns_async_client = async_client is None
        self._async_loop: asyncio.AbstractEventLoop | None = None

    @classmethod
    def from_env(cls) -> TypeSafeJevBackend:
        return cls(JevConfig.from_env())

    def build_payload(self, req: BackendRequest) -> dict[str, Any]:
        questions: dict[str, Any] = {}
        for q in req.questions:
            spec: dict[str, Any] = {"type": "noul", "instructions": q.instructions}
            if q.criteria is not None:
                spec["criteria"] = {"true": q.criteria.true, "false": q.criteria.false}
            questions[q.id] = spec
        return {"state": req.state, "model": self.config.model, "questions": questions}

    def _sync_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client()
        return self._client

    def _aclient(self) -> httpx.AsyncClient:
        # An AsyncClient's connection pool belongs to the loop that created it. Hosts that call
        # asyncio.run() per task get a fresh loop each time, so an owned client follows the loop.
        loop = asyncio.get_running_loop()
        if self._owns_async_client and self._async_loop is not loop:
            self._async_client = None
        if self._async_client is None:
            self._async_client = httpx.AsyncClient()
            self._async_loop = loop
        return self._async_client

    def _read_within(self, response: httpx.Response, attempts: _Attempts) -> bytes:
        """Read a streamed body, enforcing the total deadline between chunks."""
        chunks = []
        for chunk in response.iter_bytes():
            if attempts.remaining() <= 0:
                raise httpx.ReadTimeout("time budget exhausted while reading the response")
            chunks.append(chunk)
        return b"".join(chunks)

    async def _apost(
        self, client: httpx.AsyncClient, payload: dict[str, Any], timeout: float
    ) -> tuple[httpx.Response, bytes]:
        response = await client.post(
            self._url, json=payload, headers=self._headers, timeout=timeout
        )
        return response, response.content

    def answer(self, req: BackendRequest) -> BackendResult:
        payload = self.build_payload(req)
        attempts = _Attempts(self.config)
        client = self._sync_client()
        while True:
            remaining = attempts.remaining()
            if remaining <= 0:
                raise attempts.timeout_error()
            try:
                request = client.build_request(
                    "POST", self._url, json=payload, headers=self._headers, timeout=remaining
                )
                response = client.send(request, stream=True)
                try:
                    content = self._read_within(response, attempts)
                finally:
                    response.close()
            except httpx.TransportError as exc:
                outcome: BackendResult | float = attempts.transport_failure(exc)
            else:
                outcome = attempts.handle(response, content, req.questions)
            if isinstance(outcome, BackendResult):
                return outcome
            time.sleep(outcome)

    async def answer_async(self, req: BackendRequest) -> BackendResult:
        payload = self.build_payload(req)
        attempts = _Attempts(self.config)
        client = self._aclient()
        while True:
            remaining = attempts.remaining()
            if remaining <= 0:
                raise attempts.timeout_error()
            try:
                # wait_for makes the budget a wall clock: httpx timeouts are per phase.
                response, content = await asyncio.wait_for(
                    self._apost(client, payload, remaining), timeout=remaining
                )
            except (httpx.TransportError, asyncio.TimeoutError) as exc:
                outcome: BackendResult | float = attempts.transport_failure(exc)
            else:
                outcome = attempts.handle(response, content, req.questions)
            if isinstance(outcome, BackendResult):
                return outcome
            await asyncio.sleep(outcome)

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    async def aclose(self) -> None:
        if self._owns_async_client and self._async_client is not None:
            if self._async_loop is asyncio.get_running_loop():
                await self._async_client.aclose()
            self._async_client = None
            self._async_loop = None
        self.close()
