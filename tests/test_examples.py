"""Smoke-test the runnable examples with the offline replay backend."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def replay_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DUTYGATE_PACK", str(ROOT / "packs" / "legal-triggers.yaml"))
    monkeypatch.setenv("DUTYGATE_BACKEND", "replay")
    monkeypatch.setenv("DUTYGATE_FIXTURES", str(ROOT / "conformance" / "cases.json"))


def load(relpath: str) -> ModuleType:
    path = ROOT / "examples" / relpath
    name = "example_" + relpath.replace("/", "_").removesuffix(".py")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_fastapi_webhook() -> None:
    from fastapi.testclient import TestClient

    mod = load("fastapi_webhook/app.py")
    with TestClient(mod.app) as client:
        routed = client.post(
            "/webhook", json={"message": "pls stop texting me", "conversation_id": "c1"}
        ).json()
        assert routed["action"] == "route"
        assert routed["reply"].startswith("Thanks for your message")
        normal = client.post("/webhook", json={"message": "where is my order?"}).json()
        assert normal["action"] == "continue" and normal["reply"].startswith("(bot)")
    assert mod.CASES[-1]["queue"] == "compliance"


def test_flask_webhook() -> None:
    mod = load("flask_webhook/app.py")
    client = mod.app.test_client()
    routed = client.post("/webhook", json={"message": "I'm getting my lawyer involved"}).get_json()
    assert routed["action"] == "route"
    review = client.post("/webhook", json={"message": "please help, case for backend_timeout"})
    body = review.get_json()
    assert body["action"] == "review" and body["reply"].startswith("(bot)")
    assert mod.RESCAN[-1] == "please help, case for backend_timeout"
    assert client.post("/webhook", json={}).status_code == 400


def test_langchain_bot() -> None:
    mod = load("langchain_bot/bot.py")
    bot = mod.build_bot(mod.default_model(), mod.load_gate())
    held = bot.invoke({"input": "pls stop texting me"})
    assert held.content.startswith("Thanks for your message")
    assert mod.CASES[-1] == {"queue": "compliance", "category": "opt_out"}
    normal = bot.invoke({"input": "where is my order?"})
    assert normal.content == "Happy to help with that!"


def test_langgraph_bot() -> None:
    from langchain_core.messages import HumanMessage

    mod = load("langgraph_bot/graph.py")
    app = mod.build_graph(mod.default_model(), mod.load_gate("legal-triggers"))
    held = app.invoke({"messages": [HumanMessage("pls stop texting me")]})
    assert held["messages"][-1].content.startswith("Thanks for your message")
    assert held["dutygate"]["action"] == "route"
    assert mod.CASES[-1]["queue"] == "compliance"
    normal = app.invoke({"messages": [HumanMessage("where is my order?")]})
    assert normal["messages"][-1].content == "Happy to help with that!"
