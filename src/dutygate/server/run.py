from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from .logs import log_config


def keys_from_env(env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    raw = (os.environ if env is None else env).get("DUTYGATE_SIDECAR_KEYS", "")
    return tuple(k.strip() for k in raw.split(",") if k.strip())


def run_uvicorn(app: Any, host: str, port: int, log_level: str) -> None:  # pragma: no cover
    import uvicorn

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_config=log_config(log_level),
        log_level=log_level,
        server_header=False,
    )
