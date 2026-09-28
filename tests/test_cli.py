import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from click.testing import CliRunner

from dutygate.cli import main

from .helpers import THREE_RULES

ROOT = Path(__file__).resolve().parents[1]
PACK = str(ROOT / "packs" / "legal-triggers.yaml")


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def keywords(tmp_path: Path) -> str:
    p = tmp_path / "kw.yaml"
    p.write_text(
        yaml.safe_dump({"opt_out": [r"\bstop\b", "unsubscribe"], "legal_threat": ["lawyer"]}),
        encoding="utf-8",
    )
    return str(p)


def write_pack(tmp_path: Path, data: dict[str, Any]) -> str:
    p = tmp_path / "pack.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return str(p)


def run_json(runner: CliRunner, args: list[str], **kw: Any) -> tuple[int, dict[str, Any]]:
    res = runner.invoke(main, args, **kw)
    lines = res.stdout.strip().splitlines()
    assert len(lines) == 1, res.output
    return res.exit_code, json.loads(lines[0])


# ---------- validate ----------


def test_validate_good_pack(runner: CliRunner) -> None:
    res = runner.invoke(main, ["validate", PACK])
    assert res.exit_code == 0, res.output
    assert "ok" in res.stdout
    assert "legal-triggers 0.2.0" in res.stdout


def test_validate_bad_pack_lists_every_error(runner: CliRunner, tmp_path: Path) -> None:
    data = json.loads(json.dumps(THREE_RULES))
    data["rules"][0]["questions"] = ["q_missing"]
    data["redaction"] = [{"name": "broken", "pattern": "([a-z"}]
    res = runner.invoke(main, ["validate", write_pack(tmp_path, data)])
    assert res.exit_code == 1
    assert "q_missing" in res.stderr and "broken" in res.stderr


def test_validate_prints_warnings_on_stderr(runner: CliRunner, tmp_path: Path) -> None:
    data = json.loads(json.dumps(THREE_RULES))
    data["defaults"] = {"on_error": "continue"}
    res = runner.invoke(main, ["validate", write_pack(tmp_path, data)])
    assert res.exit_code == 0
    assert "fails open" in res.stderr


def test_validate_several_packs(runner: CliRunner, tmp_path: Path) -> None:
    res = runner.invoke(main, ["validate", PACK, write_pack(tmp_path, THREE_RULES)])
    assert res.exit_code == 0
    assert res.stdout.count("ok") == 2


def test_validate_missing_file(runner: CliRunner, tmp_path: Path) -> None:
    res = runner.invoke(main, ["validate", str(tmp_path / "nope.yaml")])
    assert res.exit_code == 1
    assert "not found" in res.stderr


# ---------- run ----------


def test_run_keyword_route(runner: CliRunner, keywords: str) -> None:
    code, out = run_json(
        runner,
        ["run", PACK, "--backend", "keyword", "--keywords", keywords, "--state", "stop texting me"],
    )
    assert code == 0
    assert out["action"] == "route"
    assert out["primary"] == "opt_out"
    assert out["backend"] == {"name": "keyword", "model": "keyword"}


def test_run_reads_stdin(runner: CliRunner, keywords: str) -> None:
    _, out = run_json(
        runner,
        ["run", PACK, "--backend", "keyword", "--keywords", keywords, "--state", "-"],
        input="my LAWYER will call\n",
    )
    assert out["primary"] == "legal_threat"


@pytest.mark.parametrize(("message", "exit_code"), [("stop", 10), ("hello there", 0)])
def test_run_exit_code_flag(runner: CliRunner, keywords: str, message: str, exit_code: int) -> None:
    res = runner.invoke(
        main,
        [
            "run",
            PACK,
            "--backend",
            "keyword",
            "--keywords",
            keywords,
            "--state",
            message,
            "--exit-code",
        ],
    )
    assert res.exit_code == exit_code


def test_run_exit_code_review(runner: CliRunner, tmp_path: Path) -> None:
    fixtures = tmp_path / "f.jsonl"
    fixtures.write_text(json.dumps({"message": "hmm", "error": "backend_timeout"}) + "\n")
    res = runner.invoke(
        main,
        [
            "run",
            PACK,
            "--backend",
            "replay",
            "--fixtures",
            str(fixtures),
            "--state",
            "hmm",
            "--exit-code",
        ],
    )
    assert res.exit_code == 11
    assert json.loads(res.stdout)["error"]["code"] == "backend_timeout"


def test_run_replay_conformance_file(runner: CliRunner) -> None:
    _, out = run_json(
        runner,
        [
            "run",
            PACK,
            "--backend",
            "replay",
            "--fixtures",
            str(ROOT / "conformance/cases.json"),
            "--state",
            "pls stop texting me",
        ],
    )
    assert out["action"] == "route" and out["primary"] == "opt_out"


def test_run_replay_requires_fixtures(runner: CliRunner) -> None:
    res = runner.invoke(main, ["run", PACK, "--backend", "replay", "--state", "x"])
    assert res.exit_code == 2
    assert "--fixtures" in res.output


def test_run_keyword_requires_keywords_for_custom_packs(runner: CliRunner, tmp_path: Path) -> None:
    res = runner.invoke(
        main, ["run", write_pack(tmp_path, THREE_RULES), "--backend", "keyword", "--state", "x"]
    )
    assert res.exit_code == 2
    assert "--keywords" in res.output


def test_run_jev_without_key(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    res = runner.invoke(main, ["run", PACK, "--state", "x"])
    assert res.exit_code == 2
    assert "TYPESAFE_API_KEY" in res.output


def test_run_invalid_pack_exits_1(runner: CliRunner, tmp_path: Path, keywords: str) -> None:
    res = runner.invoke(
        main,
        [
            "run",
            str(tmp_path / "missing.yaml"),
            "--backend",
            "keyword",
            "--keywords",
            keywords,
            "--state",
            "x",
        ],
    )
    assert res.exit_code == 1


def test_run_passes_metadata_and_recent(runner: CliRunner, tmp_path: Path) -> None:
    data = json.loads(json.dumps(THREE_RULES))
    data["context"] = {"max_recent_messages": 5}
    pack = write_pack(tmp_path, data)
    kw = tmp_path / "kw.yaml"
    kw.write_text("q_a: ['yes']\n")
    _, out = run_json(
        runner,
        [
            "run",
            pack,
            "--backend",
            "keyword",
            "--keywords",
            str(kw),
            "--state",
            "yes",
            "--conversation-id",
            "c_1",
            "--channel",
            "web",
            "--recent",
            "one",
            "--recent",
            "two",
        ],
    )
    assert out["conversation_id"] == "c_1"
    assert out["action"] == "route"


def test_version_option(runner: CliRunner) -> None:
    res = runner.invoke(main, ["--version"])
    assert res.exit_code == 0 and "0.1.0" in res.stdout


def test_cli_accepts_bundled_pack_names(runner: CliRunner) -> None:
    res = runner.invoke(main, ["validate", "legal-triggers", "outbound-claims"])
    assert res.exit_code == 0, res.output
