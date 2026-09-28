from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from dutygate import Gate
from dutygate.server import ServerConfig, create_app

from .loader import Case, cases, document, normalize, pack, replay_backend

CASES = cases()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    gates = [Gate(pack(name), replay_backend(name)) for name in document()["packs"]]
    app = create_app(gates, ServerConfig(api_keys=("conformance",)))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gate",
        headers={"Authorization": "Bearer conformance"},
    ) as c:
        yield c


def request_body(case: Case) -> dict[str, Any]:
    return {k: v for k, v in case.input.items() if v is not None}


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
async def test_sidecar_reproduces_case(client: httpx.AsyncClient, case: Case) -> None:
    res = await client.post(f"/v1/packs/{case.pack}/gate", json=request_body(case))
    assert res.status_code == 200, res.text
    assert normalize(res.json()) == case.expected
