from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from dutygate import Gate, ReplayBackend, load_policy
from dutygate.server import ServerConfig, create_app

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "conformance" / "cases.json"
KEYS = ("key-one", "key-two")
AUTH = {"Authorization": "Bearer key-one"}


def make_gates() -> list[Gate]:
    gates = []
    for path in [ROOT / "packs" / "legal-triggers.yaml", ROOT / "conformance/packs/compound.yaml"]:
        pack = load_policy(path)
        gates.append(Gate(pack, ReplayBackend.from_conformance(CASES, pack)))
    return gates


AppFactory = Callable[..., FastAPI]


@pytest.fixture
def app_factory() -> AppFactory:
    def factory(**cfg: object) -> FastAPI:
        config = ServerConfig(**{"api_keys": KEYS, **cfg})  # type: ignore[arg-type]
        return create_app(make_gates(), config)

    return factory


@pytest.fixture
async def client(app_factory: AppFactory) -> AsyncIterator[httpx.AsyncClient]:
    app = app_factory()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gate"
    ) as c:
        yield c
