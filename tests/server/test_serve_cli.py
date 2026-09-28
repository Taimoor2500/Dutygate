import json
import logging
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from dutygate.cli import main
from dutygate.server.logs import JsonFormatter, log_config

from .conftest import CASES, ROOT

LT = str(ROOT / "packs" / "legal-triggers.yaml")
CP = str(ROOT / "conformance" / "packs" / "compound.yaml")


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def fake_run(app: Any, host: str, port: int, log_level: str) -> None:
        seen.update(app=app, host=host, port=port, log_level=log_level)

    monkeypatch.setattr("dutygate.server.run.run_uvicorn", fake_run)
    return seen


def invoke(args: list[str], env: dict[str, str] | None = None) -> Any:
    return CliRunner().invoke(main, ["serve", *args], env=env or {})


def test_serve_needs_keys(captured: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DUTYGATE_SIDECAR_KEYS", raising=False)
    res = invoke([LT, "--backend", "replay", "--fixtures", str(CASES)])
    assert res.exit_code == 2
    assert "DUTYGATE_SIDECAR_KEYS" in res.output
    assert captured == {}


def test_serve_with_keys(captured: dict[str, Any]) -> None:
    res = invoke(
        [LT, CP, "--backend", "replay", "--fixtures", str(CASES), "--port", "9001"],
        env={"DUTYGATE_SIDECAR_KEYS": "a, b"},
    )
    assert res.exit_code == 0, res.output
    assert (captured["host"], captured["port"]) == ("127.0.0.1", 9001)


def test_insecure_no_auth_only_on_localhost(captured: dict[str, Any]) -> None:
    res = invoke(
        [
            LT,
            "--backend",
            "replay",
            "--fixtures",
            str(CASES),
            "--insecure-no-auth",
            "--host",
            "0.0.0.0",
        ]
    )
    assert res.exit_code == 2
    assert "127.0.0.1" in res.output
    res = invoke([LT, "--backend", "replay", "--fixtures", str(CASES), "--insecure-no-auth"])
    assert res.exit_code == 0, res.output


def test_serve_jev_without_key(captured: dict[str, Any]) -> None:
    res = invoke([LT], env={"DUTYGATE_SIDECAR_KEYS": "k", "TYPESAFE_API_KEY": ""})
    assert res.exit_code == 2
    assert "TYPESAFE_API_KEY" in res.output


def test_serve_bad_timeout_env(captured: dict[str, Any]) -> None:
    res = invoke(
        [LT],
        env={
            "DUTYGATE_SIDECAR_KEYS": "k",
            "TYPESAFE_API_KEY": "t",
            "DUTYGATE_TIMEOUT_MS": "abc",
        },
    )
    assert res.exit_code == 2
    assert "DUTYGATE_TIMEOUT_MS" in res.output


def test_serve_keywords_per_pack(captured: dict[str, Any], tmp_path: Path) -> None:
    kw1 = tmp_path / "a.yaml"
    kw1.write_text("opt_out: ['stop']\n")
    kw2 = tmp_path / "b.yaml"
    kw2.write_text("erasure: ['delete']\n")
    env = {"DUTYGATE_SIDECAR_KEYS": "k"}
    ok = invoke(
        [LT, CP, "--backend", "keyword", "--keywords", str(kw1), "--keywords", str(kw2)], env=env
    )
    assert ok.exit_code == 0, ok.output
    bad = invoke(
        [
            LT,
            CP,
            "--backend",
            "keyword",
            "--keywords",
            str(kw1),
            "--keywords",
            str(kw2),
            "--keywords",
            str(kw1),
        ],
        env=env,
    )
    assert bad.exit_code == 2


def test_serve_invalid_pack(captured: dict[str, Any], tmp_path: Path) -> None:
    res = invoke([str(tmp_path / "missing.yaml")], env={"DUTYGATE_SIDECAR_KEYS": "k"})
    assert res.exit_code == 1


def test_serve_audit_options(captured: dict[str, Any], tmp_path: Path) -> None:
    res = invoke(
        [
            LT,
            "--backend",
            "replay",
            "--fixtures",
            str(CASES),
            "--audit-log",
            str(tmp_path / "a.jsonl"),
            "--audit-include-message",
        ],
        env={"DUTYGATE_SIDECAR_KEYS": "k"},
    )
    assert res.exit_code == 0, res.output


def test_json_formatter() -> None:
    record = logging.LogRecord("dutygate.server", logging.INFO, __file__, 1, "decision", None, None)
    record.request_id = "r1"
    record.action = "route"
    data = json.loads(JsonFormatter().format(record))
    assert data["msg"] == "decision" and data["request_id"] == "r1" and data["action"] == "route"
    assert data["level"] == "info" and "ts" in data


def test_json_formatter_exception() -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        import sys

        record = logging.LogRecord(
            "dutygate", logging.ERROR, __file__, 1, "failed", None, sys.exc_info()
        )
    assert "RuntimeError" in json.loads(JsonFormatter().format(record))["exc"]


def test_log_config_is_valid() -> None:
    import logging.config

    logging.config.dictConfig(log_config("warning"))
    logging.config.dictConfig({"version": 1, "disable_existing_loggers": False})
