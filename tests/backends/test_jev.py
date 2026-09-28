import asyncio
import json
import time
from typing import Any

import httpx
import pytest
import respx

from dutygate.backends.base import BackendRequest
from dutygate.backends.jev import JevConfig, TypeSafeJevBackend, parse_response
from dutygate.errors import BackendError, ConfigError
from dutygate.schema import Pack, load_policy

URL = "https://api.typesafe.ai/v1/systemone"

PACK_DATA: dict[str, Any] = {
    "schema_version": 1,
    "name": "mini",
    "version": "0.1.0",
    "questions": [
        {
            "id": "q_optout",
            "instructions": "Does the customer ask to stop messages?",
            "criteria": {"true": "asks to stop", "false": "does not"},
        },
        {"id": "q_threat", "instructions": "Does the customer threaten legal action?"},
    ],
    "rules": [
        {
            "id": "opt-out",
            "category": "opt_out",
            "questions": ["q_optout"],
            "queue": "compliance",
            "priority": "high",
        },
        {
            "id": "threat",
            "category": "legal_threat",
            "questions": ["q_threat"],
            "queue": "legal",
            "priority": "urgent",
        },
    ],
}


@pytest.fixture
def pack() -> Pack:
    return load_policy(PACK_DATA)


def req(pack: Pack, message: str = "stop texting me") -> BackendRequest:
    return BackendRequest(state={"customer_message": message}, questions=pack.questions)


def ok_body(optout: float = 0.9, threat: float = 0.1, model: str = "jev-1.13.0") -> dict[str, Any]:
    return {
        "model": model,
        "answers": {
            "q_optout": {"type": "noul", "noul": optout},
            "q_threat": {"type": "noul", "noul": threat},
        },
        "usage": {"input_tokens": 10, "output_tokens": 2},
    }


def backend(**cfg: Any) -> TypeSafeJevBackend:
    return TypeSafeJevBackend(JevConfig(api_key="sk-test", **cfg))


def code_of(fn: Any) -> str:
    with pytest.raises(BackendError) as exc:
        fn()
    return exc.value.code


# ---------- payload ----------


def test_payload_matches_typesafe_api(pack: Pack) -> None:
    payload = backend(model="jev-1.13.0").build_payload(req(pack))
    assert payload == {
        "state": {"customer_message": "stop texting me"},
        "model": "jev-1.13.0",
        "questions": {
            "q_optout": {
                "type": "noul",
                "instructions": "Does the customer ask to stop messages?",
                "criteria": {"true": "asks to stop", "false": "does not"},
            },
            "q_threat": {
                "type": "noul",
                "instructions": "Does the customer threaten legal action?",
            },
        },
    }


@respx.mock
def test_success_and_headers(pack: Pack) -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=ok_body()))
    res = backend().answer(req(pack))
    assert res.scores == {"q_optout": 0.9, "q_threat": 0.1}
    assert res.model == "jev-1.13.0"
    sent = route.calls.last.request
    assert sent.headers["authorization"] == "Bearer sk-test"
    assert sent.headers["content-type"] == "application/json"
    assert sent.headers["user-agent"].startswith("dutygate/")
    assert json.loads(sent.content)["model"] == "jev-latest"


@respx.mock
def test_custom_base_url(pack: Pack) -> None:
    respx.post("https://jev.internal/v1/systemone").mock(
        return_value=httpx.Response(200, json=ok_body())
    )
    assert backend(base_url="https://jev.internal/").answer(req(pack)).scores["q_optout"] == 0.9


# ---------- status mapping ----------


@respx.mock
@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "backend_auth"),
        (403, "backend_auth"),
        (422, "backend_rejected"),
        (400, "backend_rejected"),
    ],
)
def test_client_errors_not_retried(pack: Pack, status: int, code: str) -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(status, json={"error": "x"}))
    assert code_of(lambda: backend(max_retries=3).answer(req(pack))) == code
    assert route.call_count == 1


@respx.mock
def test_429_then_success(pack: Pack) -> None:
    route = respx.post(URL).mock(
        side_effect=[httpx.Response(429), httpx.Response(200, json=ok_body())]
    )
    assert backend().answer(req(pack)).scores["q_optout"] == 0.9
    assert route.call_count == 2


@respx.mock
def test_529_exhausts_retries(pack: Pack) -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(529))
    assert code_of(lambda: backend(max_retries=1).answer(req(pack))) == "backend_unavailable"
    assert route.call_count == 2


@respx.mock
def test_500_retried(pack: Pack) -> None:
    route = respx.post(URL).mock(
        side_effect=[httpx.Response(500), httpx.Response(200, json=ok_body())]
    )
    backend().answer(req(pack))
    assert route.call_count == 2


@respx.mock
def test_connection_error_retried_then_unavailable(pack: Pack) -> None:
    route = respx.post(URL).mock(side_effect=httpx.ConnectError("refused"))
    assert code_of(lambda: backend(max_retries=2).answer(req(pack))) == "backend_unavailable"
    assert route.call_count == 3


@respx.mock
def test_zero_retries(pack: Pack) -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(529))
    assert code_of(lambda: backend(max_retries=0).answer(req(pack))) == "backend_unavailable"
    assert route.call_count == 1


@respx.mock
def test_deadline_exceeded_is_timeout(pack: Pack) -> None:
    respx.post(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    started = time.monotonic()
    assert (
        code_of(lambda: backend(timeout_ms=50, max_retries=5).answer(req(pack)))
        == "backend_timeout"
    )
    assert time.monotonic() - started < 1.0


@respx.mock
def test_retry_after_longer_than_budget_gives_up(pack: Pack) -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(429, headers={"Retry-After": "30"}))
    started = time.monotonic()
    assert code_of(lambda: backend(timeout_ms=5000).answer(req(pack))) == "backend_unavailable"
    assert time.monotonic() - started < 1.0
    assert route.call_count == 1


@respx.mock
def test_error_message_has_status_but_not_body(pack: Pack) -> None:
    respx.post(URL).mock(return_value=httpx.Response(401))
    with pytest.raises(BackendError) as exc:
        backend().answer(req(pack, "secret-sentinel"))
    assert "401" in exc.value.message
    assert "secret-sentinel" not in exc.value.message


# ---------- malformed ----------


@respx.mock
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, json={"model": "jev"}),
        httpx.Response(200, json={"answers": []}),
        httpx.Response(
            200,
            json={
                "answers": {
                    "q_optout": {"type": "choice", "choice": "a"},
                    "q_threat": {"type": "noul", "noul": 0.1},
                }
            },
        ),
        httpx.Response(
            200,
            json={
                "answers": {
                    "q_optout": {"type": "noul", "noul": "0.9"},
                    "q_threat": {"type": "noul", "noul": 0.1},
                }
            },
        ),
        httpx.Response(200, json={"answers": {"q_threat": {"type": "noul", "noul": 0.1}}}),
        httpx.Response(200, json=[1, 2]),
    ],
)
def test_malformed_responses(pack: Pack, response: httpx.Response) -> None:
    respx.post(URL).mock(return_value=response)
    assert code_of(lambda: backend().answer(req(pack))) == "malformed_response"


def test_parse_response_passes_out_of_range_through(pack: Pack) -> None:
    # Range checks belong to the engine, so every backend is validated the same way.
    body = ok_body(optout=1.7)
    assert parse_response(body, pack.questions).scores["q_optout"] == 1.7


# ---------- async ----------


@respx.mock
async def test_async_success(pack: Pack) -> None:
    respx.post(URL).mock(return_value=httpx.Response(200, json=ok_body(optout=0.8)))
    b = backend()
    assert (await b.answer_async(req(pack))).scores["q_optout"] == 0.8
    await b.aclose()


@respx.mock
async def test_async_retry(pack: Pack) -> None:
    route = respx.post(URL).mock(
        side_effect=[httpx.Response(429), httpx.Response(200, json=ok_body())]
    )
    await backend().answer_async(req(pack))
    assert route.call_count == 2


@respx.mock
async def test_async_timeout(pack: Pack) -> None:
    respx.post(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(BackendError) as exc:
        await backend(timeout_ms=50, max_retries=5).answer_async(req(pack))
    assert exc.value.code == "backend_timeout"


@respx.mock
async def test_concurrent_calls_do_not_cross_talk(pack: Pack) -> None:
    def echo(request: httpx.Request) -> httpx.Response:
        message = json.loads(request.content)["state"]["customer_message"]
        n = int(message.split("-")[1])
        return httpx.Response(200, json=ok_body(optout=n / 100))

    respx.post(URL).mock(side_effect=echo)
    b = backend()
    results = await asyncio.gather(*(b.answer_async(req(pack, f"msg-{i}")) for i in range(50)))
    assert [r.scores["q_optout"] for r in results] == [i / 100 for i in range(50)]
    await b.aclose()


# ---------- config ----------


def test_config_from_env_defaults() -> None:
    cfg = JevConfig.from_env({"TYPESAFE_API_KEY": "k"})
    assert cfg == JevConfig(api_key="k")


def test_config_from_env_overrides() -> None:
    cfg = JevConfig.from_env(
        {
            "TYPESAFE_API_KEY": "k",
            "TYPESAFE_BASE_URL": "https://x.test",
            "DUTYGATE_JEV_MODEL": "jev-1.13.0",
            "DUTYGATE_TIMEOUT_MS": "800",
            "DUTYGATE_MAX_RETRIES": "0",
        }
    )
    assert (cfg.base_url, cfg.model, cfg.timeout_ms, cfg.max_retries) == (
        "https://x.test",
        "jev-1.13.0",
        800,
        0,
    )


@pytest.mark.parametrize(
    ("env", "var"),
    [
        ({}, "TYPESAFE_API_KEY"),
        ({"TYPESAFE_API_KEY": "  "}, "TYPESAFE_API_KEY"),
        ({"TYPESAFE_API_KEY": "k", "DUTYGATE_TIMEOUT_MS": "abc"}, "DUTYGATE_TIMEOUT_MS"),
        ({"TYPESAFE_API_KEY": "k", "DUTYGATE_TIMEOUT_MS": "0"}, "DUTYGATE_TIMEOUT_MS"),
        ({"TYPESAFE_API_KEY": "k", "DUTYGATE_MAX_RETRIES": "-1"}, "DUTYGATE_MAX_RETRIES"),
        ({"TYPESAFE_API_KEY": "k", "TYPESAFE_BASE_URL": "ftp://x"}, "TYPESAFE_BASE_URL"),
    ],
)
def test_bad_config_names_variable(env: dict[str, str], var: str) -> None:
    with pytest.raises(ConfigError, match=var):
        JevConfig.from_env(env)


def test_backend_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    b = TypeSafeJevBackend.from_env()
    assert b.config.api_key == "k"
    b.close()


def test_repr_hides_key() -> None:
    assert "sk-test" not in repr(JevConfig(api_key="sk-test"))


class _SlowStream(httpx.SyncByteStream, httpx.AsyncByteStream):
    def __init__(self, body: bytes, pieces: int = 6, delay: float = 0.2) -> None:
        size = -(-len(body) // pieces)
        self.chunks = [body[i : i + size] for i in range(0, len(body), size)]
        self.delay = delay

    def __iter__(self):  # type: ignore[no-untyped-def]
        for c in self.chunks:
            time.sleep(self.delay)
            yield c

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        for c in self.chunks:
            await asyncio.sleep(self.delay)
            yield c


def _slow_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        stream=_SlowStream(json.dumps(ok_body()).encode()),
        headers={"content-type": "application/json"},
    )


@respx.mock
def test_slow_streaming_response_respects_total_budget(pack: Pack) -> None:
    respx.post(URL).mock(side_effect=_slow_response)
    started = time.monotonic()
    assert code_of(lambda: backend(timeout_ms=300, max_retries=0).answer(req(pack))) == (
        "backend_timeout"
    )
    assert time.monotonic() - started < 0.7


@respx.mock
async def test_slow_streaming_response_respects_total_budget_async(pack: Pack) -> None:
    respx.post(URL).mock(side_effect=_slow_response)
    started = time.monotonic()
    with pytest.raises(BackendError) as exc:
        await backend(timeout_ms=300, max_retries=0).answer_async(req(pack))
    assert exc.value.code == "backend_timeout"
    assert time.monotonic() - started < 0.7


def test_async_client_recreated_for_a_new_event_loop() -> None:
    b = backend()

    async def grab() -> object:
        return b._aclient()

    first = asyncio.run(grab())
    second = asyncio.run(grab())
    assert first is not second
