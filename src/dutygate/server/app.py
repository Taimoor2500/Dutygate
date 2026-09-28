from __future__ import annotations

import hmac
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, MutableMapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from .._version import __version__
from ..errors import ConfigError
from ..gate import Gate
from .audit import AuditLog
from .metrics import GateMetrics

logger = logging.getLogger("dutygate.server")

REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


@dataclass(frozen=True)
class ServerConfig:
    api_keys: tuple[str, ...]
    insecure_no_auth: bool = False
    audit_log: Path | None = None
    audit_include_message: bool = False
    max_body_bytes: int = 1_048_576


class GateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: Annotated[StrictStr, Field(min_length=1)]
    conversation_id: Annotated[StrictStr, Field(max_length=256)] | None = None
    channel: Annotated[StrictStr, Field(max_length=64)] | None = None
    recent_messages: Annotated[list[StrictStr], Field(max_length=20)] | None = None


class BodyLimit:
    """Reject request bodies over the limit, whether or not Content-Length is sent."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers", []):
            if name == b"content-length" and value.isdigit() and int(value) > self.max_bytes:
                await JSONResponse({"detail": "request body too large"}, 413)(scope, receive, send)
                return
        received = 0

        async def limited() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise HTTPException(413, "request body too large")
            return message

        await self.app(scope, limited, send)


def _check_keys(config: ServerConfig) -> Callable[[Request], None]:
    keys = [k.encode() for k in config.api_keys]

    def check(request: Request) -> None:
        if config.insecure_no_auth:
            return
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        supplied = token.strip().encode()
        ok = scheme.lower() == "bearer" and bool(supplied)
        # Compare against every key so timing does not reveal which key (if any) matched.
        matched = False
        for key in keys:
            matched |= hmac.compare_digest(supplied, key)
        if not (ok and matched):
            raise HTTPException(
                401, "invalid or missing API key", headers={"WWW-Authenticate": "Bearer"}
            )

    return check


def create_app(gates: Sequence[Gate], config: ServerConfig) -> FastAPI:
    if not gates:
        raise ValueError("create_app needs at least one gate")
    if not config.api_keys and not config.insecure_no_auth:
        raise ConfigError(
            "no sidecar API keys configured: set DUTYGATE_SIDECAR_KEYS "
            "(comma-separated) or pass --insecure-no-auth for local development"
        )
    by_name: dict[str, Gate] = {}
    for gate in gates:
        if gate.pack.name in by_name:
            raise ValueError(f"pack '{gate.pack.name}' is loaded twice")
        by_name[gate.pack.name] = gate
    default = gates[0]
    metrics = GateMetrics()
    audit = (
        AuditLog(config.audit_log, include_message=config.audit_include_message)
        if config.audit_log
        else None
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        for gate in gates:
            try:
                await gate.aclose()
            except Exception:
                logger.exception("failed to close backend", extra={"pack": gate.pack.name})

    app = FastAPI(
        title="DutyGate sidecar",
        version=__version__,
        description="Flags legal and compliance triggers in inbound messages.",
        lifespan=lifespan,
    )
    app.add_middleware(BodyLimit, max_bytes=config.max_body_bytes)
    authorized = Depends(_check_keys(config))

    @app.middleware("http")
    async def request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        supplied = request.headers.get("x-request-id", "")
        rid = supplied if REQUEST_ID.match(supplied) else uuid.uuid4().hex
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Drop the offending input from the error body so message text is never echoed.
        errors = [
            {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        return JSONResponse({"detail": errors}, status_code=422)

    async def judge(gate: Gate, body: GateRequest, request: Request) -> dict[str, Any]:
        started = time.perf_counter()
        decision = await gate.check_async(
            body.message,
            conversation_id=body.conversation_id,
            channel=body.channel,
            recent_messages=body.recent_messages,
        )
        metrics.observe(gate.pack.name, decision, time.perf_counter() - started)
        rid: str = request.state.request_id
        logger.info(
            "decision",
            extra={
                "request_id": rid,
                "pack": gate.pack.name,
                "action": decision.action,
                "error_code": decision.error.code if decision.error else None,
                "latency_ms": decision.latency_ms,
            },
        )
        if audit is not None:
            try:
                await audit.write(
                    request_id=rid, pack=gate.pack.name, decision=decision, message=body.message
                )
            except Exception:
                # Never trade a decision for an audit record: a 500 here would turn a route
                # into a client-side review.
                metrics.audit_failures.inc()
                logger.exception(
                    "audit write failed", extra={"request_id": rid, "pack": gate.pack.name}
                )
        return decision.to_dict()

    @app.post("/v1/gate", dependencies=[authorized])
    async def gate_default(body: GateRequest, request: Request) -> dict[str, Any]:
        return await judge(default, body, request)

    @app.post("/v1/packs/{name}/gate", dependencies=[authorized])
    async def gate_named(name: str, body: GateRequest, request: Request) -> dict[str, Any]:
        gate = by_name.get(name)
        if gate is None:
            raise HTTPException(404, f"unknown pack '{name}'")
        return await judge(gate, body, request)

    @app.get("/v1/policy", dependencies=[authorized])
    async def policy() -> dict[str, Any]:
        return {
            "default": default.pack.name,
            "packs": [
                {
                    "name": g.pack.name,
                    "version": g.pack.version,
                    "description": g.pack.description,
                    "backend": g.backend.name,
                    "rules": [
                        {
                            "id": r.id,
                            "category": r.category,
                            "queue": r.queue,
                            "priority": r.priority,
                        }
                        for r in g.pack.rules
                    ],
                }
                for g in gates
            ],
        }

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> dict[str, Any]:
        return {
            "status": "ready",
            "packs": [{"name": g.pack.name, "version": g.pack.version} for g in gates],
        }

    @app.get("/metrics")
    async def prometheus() -> Response:
        return Response(metrics.render(), media_type=CONTENT_TYPE_LATEST)

    return app
