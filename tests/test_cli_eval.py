import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from dutygate.cli import main

from .helpers import THREE_RULES


@pytest.fixture
def setup(tmp_path: Path) -> dict[str, str]:
    pack = tmp_path / "pack.yaml"
    pack.write_text(yaml.safe_dump(THREE_RULES), encoding="utf-8")
    kw = tmp_path / "kw.yaml"
    kw.write_text(yaml.safe_dump({"q_a": ["alpha"], "q_c": ["charlie"]}), encoding="utf-8")
    weak = tmp_path / "weak.yaml"
    weak.write_text(yaml.safe_dump({"q_a": ["alpha"]}), encoding="utf-8")
    ds = tmp_path / "ds.jsonl"
    rows = [
        {"id": "1", "message": "alpha", "labels": ["cat_a"], "tags": ["plain"]},
        {"id": "2", "message": "charlie", "labels": ["cat_c"], "tags": ["slang"]},
        {"id": "3", "message": "hello", "labels": [], "tags": ["plain"]},
    ]
    ds.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return {
        "pack": str(pack),
        "kw": str(kw),
        "weak": str(weak),
        "ds": str(ds),
        "dir": str(tmp_path),
    }


def test_eval_keyword_prints_table_and_report(setup: dict[str, str]) -> None:
    report = Path(setup["dir"]) / "report.json"
    res = CliRunner().invoke(
        main,
        [
            "eval",
            setup["pack"],
            setup["ds"],
            "--backend",
            "keyword",
            "--keywords",
            setup["kw"],
            "--report",
            str(report),
        ],
    )
    assert res.exit_code == 0, res.output
    assert "| caught" in res.stdout and "100.0%" in res.stdout
    data = json.loads(report.read_text())
    assert data["metrics"]["caught_rate"] == 1.0
    assert data["fail_under"] == []


def test_eval_with_baseline(setup: dict[str, str]) -> None:
    res = CliRunner().invoke(
        main,
        [
            "eval",
            setup["pack"],
            setup["ds"],
            "--backend",
            "keyword",
            "--keywords",
            setup["kw"],
            "--baseline",
            setup["weak"],
        ],
    )
    assert res.exit_code == 0, res.output
    assert "baseline" in res.stdout
    assert "50.0%" in res.stdout  # the weak baseline catches 1 of 2


def test_eval_fail_under_exits_1(setup: dict[str, str]) -> None:
    res = CliRunner().invoke(
        main,
        [
            "eval",
            setup["pack"],
            setup["ds"],
            "--backend",
            "keyword",
            "--keywords",
            setup["weak"],
            "--fail-under",
            "caught=1.0",
        ],
    )
    assert res.exit_code == 1
    assert "caught" in res.stderr


def test_eval_bad_fail_under_spec(setup: dict[str, str]) -> None:
    res = CliRunner().invoke(
        main,
        [
            "eval",
            setup["pack"],
            setup["ds"],
            "--backend",
            "keyword",
            "--keywords",
            setup["kw"],
            "--fail-under",
            "nope=1",
        ],
    )
    assert res.exit_code == 2


def test_eval_save_then_replay_and_sweep(setup: dict[str, str]) -> None:
    answers = Path(setup["dir"]) / "answers.jsonl"
    first = CliRunner().invoke(
        main,
        [
            "eval",
            setup["pack"],
            setup["ds"],
            "--backend",
            "keyword",
            "--keywords",
            setup["kw"],
            "--save-answers",
            str(answers),
        ],
    )
    assert first.exit_code == 0, first.output
    again = CliRunner().invoke(
        main, ["eval", setup["pack"], setup["ds"], "--replay", str(answers), "--sweep"]
    )
    assert again.exit_code == 0, again.output
    assert "| caught" in again.stdout
    assert "Threshold sweep" in again.stdout and "rule-a" in again.stdout


def test_eval_sweep_needs_answers(setup: dict[str, str]) -> None:
    res = CliRunner().invoke(
        main,
        [
            "eval",
            setup["pack"],
            setup["ds"],
            "--backend",
            "keyword",
            "--keywords",
            setup["kw"],
            "--sweep",
        ],
    )
    assert res.exit_code == 2
    assert "--replay" in res.output


def test_eval_unknown_label_exits_1(setup: dict[str, str]) -> None:
    ds = Path(setup["dir"]) / "bad.jsonl"
    ds.write_text(json.dumps({"id": "1", "message": "x", "labels": ["not_a_category"]}) + "\n")
    res = CliRunner().invoke(
        main, ["eval", setup["pack"], str(ds), "--backend", "keyword", "--keywords", setup["kw"]]
    )
    assert res.exit_code == 1
    assert "not_a_category" in res.stderr


def test_eval_bad_dataset_exits_1(setup: dict[str, str]) -> None:
    ds = Path(setup["dir"]) / "bad.jsonl"
    ds.write_text("{oops\n")
    res = CliRunner().invoke(
        main, ["eval", setup["pack"], str(ds), "--backend", "keyword", "--keywords", setup["kw"]]
    )
    assert res.exit_code == 1
