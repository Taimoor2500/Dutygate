import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest

from dutygate import Gate, load_policy
from dutygate.server import ServerConfig, create_app

from ..helpers import StaticBackend, make_pack, zeros
from .conftest import AUTH, ROOT, AppFactory

GATE = "/v1/gate"


async def post(
    client: httpx.AsyncClient, body: Any, path: str = GATE, headers: dict[str, str] | None = None
) -> httpx.Response:
    return await client.post(path, json=body, headers=AUTH if headers is None else headers)


# ---------- the happy path ----------


async def test_gate_returns_decision(client: httpx.AsyncClient) -> None:
    res = await post(client, {"message": "pls stop texting me", "conversation_id": "c_1"})
    assert res.status_code == 200
    body = res.json()
    assert body["action"] == "route" and body["primary"] == "opt_out"
    assert body["conversation_id"] == "c_1"
    assert body["policy"] == {"name": "legal-triggers", "version": "0.2.0"}
    assert body["id"].startswith("dec_")


async def test_channel_and_recent_messages_accepted(client: httpx.AsyncClient) -> None:
    res = await post(
        client,
        {
            "message": "STOP",
            "channel": "sms",
            "conversation_id": "c_sms_1",
            "recent_messages": ["earlier"],
        },
    )
    assert res.status_code == 200 and res.json()["action"] == "route"


async def test_second_pack_route(client: httpx.AsyncClient) -> None:
    res = await post(
        client, {"message": "delete my data right now, urgent!"}, path="/v1/packs/compound/gate"
    )
    assert res.status_code == 200
    assert res.json()["primary"] == "urgent_erasure"


async def test_default_pack_also_addressable_by_name(client: httpx.AsyncClient) -> None:
    res = await post(
        client, {"message": "pls stop texting me"}, path="/v1/packs/legal-triggers/gate"
    )
    assert res.json()["primary"] == "opt_out"


async def test_unknown_pack_404(client: httpx.AsyncClient) -> None:
    res = await post(client, {"message": "hi"}, path="/v1/packs/nope/gate")
    assert res.status_code == 404
    assert "nope" in res.json()["detail"]


async def test_backend_error_is_200_review(client: httpx.AsyncClient) -> None:
    res = await post(client, {"message": "please help, case for backend_timeout"})
    assert res.status_code == 200
    body = res.json()
    assert body["action"] == "review" and body["error"]["code"] == "backend_timeout"


# ---------- auth ----------


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong"},
        {"Authorization": "key-one"},
        {"Authorization": "Basic key-one"},
        {"Authorization": "Bearer "},
    ],
)
async def test_bad_auth_401(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    res = await post(client, {"message": "hi"}, headers=headers)
    assert res.status_code == 401
    assert res.headers["www-authenticate"] == "Bearer"


async def test_rotated_keys_both_work(client: httpx.AsyncClient) -> None:
    for key in ("key-one", "key-two"):
        res = await post(
            client, {"message": "where is my order?"}, headers={"Authorization": f"Bearer {key}"}
        )
        assert res.status_code == 200


async def test_policy_requires_auth(client: httpx.AsyncClient) -> None:
    assert (await client.get("/v1/policy")).status_code == 401


async def test_insecure_no_auth(app_factory: AppFactory) -> None:
    app = app_factory(api_keys=(), insecure_no_auth=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gate"
    ) as c:
        res = await c.post(GATE, json={"message": "where is my order?"})
    assert res.status_code == 200


def test_no_keys_without_insecure_flag_refused() -> None:
    from dutygate.errors import ConfigError

    with pytest.raises(ConfigError, match="DUTYGATE_SIDECAR_KEYS"):
        create_app([Gate(make_pack(), StaticBackend(zeros()))], ServerConfig(api_keys=()))


def test_duplicate_pack_names_refused() -> None:
    gates = [Gate(make_pack(), StaticBackend(zeros())), Gate(make_pack(), StaticBackend(zeros()))]
    with pytest.raises(ValueError, match="three"):
        create_app(gates, ServerConfig(api_keys=("k",)))


# ---------- validation ----------


@pytest.mark.parametrize(
    "body",
    [
        {"message": ""},
        {"message": None},
        {},
        {"message": 42},
        {"message": "ok", "recent_messages": ["ok", 3]},
        {"message": "ok", "recent_messages": ["x"] * 21},
        {"message": "ok", "extra_field": 1},
        {"message": "ok", "conversation_id": "c" * 257},
        {"message": "ok", "channel": "x" * 65},
        ["not", "an", "object"],
    ],
)
async def test_invalid_bodies_422(client: httpx.AsyncClient, body: Any) -> None:
    res = await post(client, body)
    assert res.status_code == 422


async def test_invalid_json_422(client: httpx.AsyncClient) -> None:
    res = await client.post(
        GATE, content=b"{nope", headers={**AUTH, "content-type": "application/json"}
    )
    assert res.status_code == 422


async def test_body_too_large_413(client: httpx.AsyncClient) -> None:
    res = await post(client, {"message": "x" * 2_000_000})
    assert res.status_code == 413


async def test_body_too_large_without_content_length(client: httpx.AsyncClient) -> None:
    async def chunks() -> Any:
        for _ in range(3):
            yield b"x" * 600_000

    res = await client.post(
        GATE, content=chunks(), headers={**AUTH, "content-type": "application/json"}
    )
    assert res.status_code == 413


async def test_over_pack_limit_is_review_not_413(client: httpx.AsyncClient) -> None:
    res = await post(client, {"message": "x" * 8001})
    assert res.status_code == 200
    assert res.json()["error"]["code"] == "message_too_long"


# ---------- operational endpoints ----------


async def test_healthz_no_auth(client: httpx.AsyncClient) -> None:
    res = await client.get("/healthz")
    assert res.status_code == 200 and res.json() == {"status": "ok"}


async def test_readyz_lists_packs(client: httpx.AsyncClient) -> None:
    res = await client.get("/readyz")
    assert res.status_code == 200
    assert res.json()["packs"] == [
        {"name": "legal-triggers", "version": "0.2.0"},
        {"name": "compound", "version": "1.0.0"},
    ]


async def test_policy_summary(client: httpx.AsyncClient) -> None:
    res = await client.get("/v1/policy", headers=AUTH)
    body = res.json()
    assert body["default"] == "legal-triggers"
    lt = body["packs"][0]
    assert lt["rules"][0] == {
        "id": "legal-threat",
        "category": "legal_threat",
        "queue": "legal",
        "priority": "urgent",
    }
    assert "questions" not in lt


async def test_metrics(client: httpx.AsyncClient) -> None:
    await post(client, {"message": "pls stop texting me"})
    await post(client, {"message": "please help, case for backend_timeout"})
    text = (await client.get("/metrics")).text
    assert 'dutygate_decisions_total{action="route",pack="legal-triggers"} 1.0' in text
    assert 'dutygate_errors_total{code="backend_timeout",pack="legal-triggers"} 1.0' in text
    assert "dutygate_decision_seconds_bucket" in text


async def test_metrics_isolated_per_app(app_factory: AppFactory) -> None:
    for _ in range(2):
        app = app_factory()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gate"
        ) as c:
            await c.post(GATE, json={"message": "pls stop texting me"}, headers=AUTH)
            text = (await c.get("/metrics")).text
        assert 'dutygate_decisions_total{action="route",pack="legal-triggers"} 1.0' in text


async def test_request_id_echoed_or_generated(client: httpx.AsyncClient) -> None:
    res = await post(client, {"message": "hi"}, headers={**AUTH, "X-Request-Id": "req-123"})
    assert res.headers["x-request-id"] == "req-123"
    res = await post(client, {"message": "hi"})
    assert len(res.headers["x-request-id"]) == 32
    res = await post(client, {"message": "hi"}, headers={**AUTH, "X-Request-Id": "bad id\n!"})
    assert res.headers["x-request-id"] != "bad id\n!"


# ---------- audit and logging ----------


async def test_audit_log_without_message(app_factory: AppFactory, tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    app = app_factory(audit_log=log)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gate"
    ) as c:
        await c.post(
            GATE, json={"message": "pls stop texting me"}, headers={**AUTH, "X-Request-Id": "r1"}
        )
        await c.post(GATE, json={"message": "where is my order?"}, headers=AUTH)
    lines = [json.loads(x) for x in log.read_text().splitlines()]
    assert len(lines) == 2
    assert lines[0]["request_id"] == "r1" and lines[0]["pack"] == "legal-triggers"
    assert lines[0]["decision"]["action"] == "route"
    assert "ts" in lines[0]
    assert "message" not in lines[0]
    assert "stop texting" not in log.read_text()


async def test_audit_log_with_message_opt_in(app_factory: AppFactory, tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    app = app_factory(audit_log=log, audit_include_message=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gate"
    ) as c:
        await c.post(GATE, json={"message": "pls stop texting me"}, headers=AUTH)
    assert json.loads(log.read_text())["message"] == "pls stop texting me"


async def test_message_never_logged(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    sentinel = "sentinel-7f3a delete my data"
    await post(client, {"message": sentinel})
    await post(client, {"message": sentinel, "bogus": 1})
    assert "sentinel-7f3a" not in caplog.text
    assert any(r.name == "dutygate.server" for r in caplog.records)


async def test_gates_closed_on_shutdown() -> None:
    class Closing(StaticBackend):
        aclosed = 0

        async def aclose(self) -> None:
            Closing.aclosed += 1

    app = create_app([Gate(make_pack(), Closing(zeros()))], ServerConfig(api_keys=("k",)))
    async with app.router.lifespan_context(app):
        pass
    assert Closing.aclosed == 1


def test_reference_pack_loads() -> None:
    assert load_policy(ROOT / "packs" / "legal-triggers.yaml").name == "legal-triggers"


def test_unwritable_audit_log_refused_at_startup(tmp_path: Path) -> None:
    from dutygate.errors import ConfigError

    with pytest.raises(ConfigError, match="audit"):
        create_app(
            [Gate(make_pack(), StaticBackend(zeros()))],
            ServerConfig(api_keys=("k",), audit_log=tmp_path / "missing" / "a.jsonl"),
        )


async def test_audit_write_failure_still_returns_decision(
    app_factory: AppFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dutygate.server.audit import AuditLog

    def boom(self: AuditLog, line: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(AuditLog, "_append", boom)
    app = app_factory(audit_log=tmp_path / "a.jsonl")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gate"
    ) as c:
        res = await c.post(GATE, json={"message": "pls stop texting me"}, headers=AUTH)
        assert res.status_code == 200 and res.json()["action"] == "route"
        text = (await c.get("/metrics")).text
    assert "dutygate_audit_failures_total 1.0" in text


# ---------- auth runs before the body is read ----------


@pytest.mark.parametrize(
    ("content", "path"),
    [
        (b"{not json", GATE),
        (b'{"message": null}', GATE),
        (b'{"message": "hi", "extra_field": 1}', GATE),
        (b'{"message": "hi"}', "/v1/packs/no-such-pack/gate"),
        (b"x" * 2_000_000, GATE),
    ],
    ids=["malformed-json", "invalid-body", "unknown-field", "unknown-pack", "oversized-body"],
)
async def test_unauthenticated_requests_get_401_before_body_checks(
    client: httpx.AsyncClient, content: bytes, path: str
) -> None:
    res = await client.post(path, content=content, headers={"content-type": "application/json"})
    assert res.status_code == 401
    assert res.headers["www-authenticate"] == "Bearer"
    assert res.json() == {"detail": "invalid or missing API key"}
    assert res.headers["x-request-id"]


async def test_wrong_key_with_malformed_body_is_401(client: httpx.AsyncClient) -> None:
    res = await client.post(
        GATE,
        content=b"{nope",
        headers={"authorization": "Bearer wrong", "content-type": "application/json"},
    )
    assert res.status_code == 401


async def test_policy_endpoint_unauthenticated_is_401_with_request_id(
    client: httpx.AsyncClient,
) -> None:
    res = await client.get("/v1/policy", headers={"X-Request-Id": "r-auth"})
    assert res.status_code == 401
    assert res.headers["x-request-id"] == "r-auth"
