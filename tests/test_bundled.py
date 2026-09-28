"""Bundled packs, sample datasets and keyword baselines, and `dutygate init`."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from dutygate import bundled_packs
from dutygate.bundled import bundled_dataset, bundled_keywords
from dutygate.cli import main


def test_bundled_files_exist_for_every_pack() -> None:
    for name in bundled_packs():
        dataset, keywords = bundled_dataset(name), bundled_keywords(name)
        assert dataset is not None and dataset.is_file(), name
        assert keywords is not None and keywords.is_file(), name


def test_unknown_names_have_no_bundled_files() -> None:
    assert bundled_dataset("nope") is None
    assert bundled_keywords("nope") is None
    assert bundled_dataset("../packs/legal-triggers") is None


def test_run_keyword_backend_uses_bundled_keywords() -> None:
    res = CliRunner().invoke(
        main, ["run", "legal-triggers", "--backend", "keyword", "--state", "stop texting me"]
    )
    assert res.exit_code == 0, res.output
    assert json.loads(res.stdout)["action"] == "route"


def test_eval_without_dataset_uses_bundled_sample() -> None:
    res = CliRunner().invoke(main, ["eval", "legal-triggers", "--backend", "keyword"])
    assert res.exit_code == 0, res.output
    assert "Rows: 104 positive, 55 clean" in res.stdout


def test_eval_custom_pack_without_dataset_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(main, ["init", "legal-triggers"]).exit_code == 0
    Path("mine.yaml").write_text(
        Path("legal-triggers.yaml").read_text().replace("name: legal-triggers", "name: mine")
    )
    res = runner.invoke(
        main,
        [
            "eval",
            "mine.yaml",
            "--backend",
            "keyword",
            "--keywords",
            "legal-triggers.keywords.yaml",
        ],
    )
    assert res.exit_code == 2
    assert "DATASET" in res.output


def test_keyword_backend_without_bundled_keywords_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    runner.invoke(main, ["init", "legal-triggers"])
    Path("mine.yaml").write_text(
        Path("legal-triggers.yaml").read_text().replace("name: legal-triggers", "name: mine")
    )
    res = runner.invoke(main, ["run", "mine.yaml", "--backend", "keyword", "--state", "x"])
    assert res.exit_code == 2
    assert "--keywords" in res.output


def test_init_copies_pack_dataset_and_keywords(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    res = runner.invoke(main, ["init", "legal-triggers"])
    assert res.exit_code == 0, res.output
    files = sorted(p.name for p in Path(".").iterdir())
    assert files == [
        "legal-triggers.dataset.jsonl",
        "legal-triggers.keywords.yaml",
        "legal-triggers.yaml",
    ]
    assert "dutygate validate legal-triggers.yaml" in res.stdout
    assert runner.invoke(main, ["validate", "legal-triggers.yaml"]).exit_code == 0
    ev = runner.invoke(
        main,
        [
            "eval",
            "legal-triggers.yaml",
            "legal-triggers.dataset.jsonl",
            "--backend",
            "keyword",
            "--keywords",
            "legal-triggers.keywords.yaml",
        ],
    )
    assert ev.exit_code == 0, ev.output


def test_init_into_directory(tmp_path: Path) -> None:
    res = CliRunner().invoke(main, ["init", "outbound-claims", "--dir", str(tmp_path / "packs")])
    assert res.exit_code == 0, res.output
    assert (tmp_path / "packs" / "outbound-claims.yaml").is_file()


def test_init_refuses_to_overwrite_without_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    runner.invoke(main, ["init", "legal-triggers"])
    Path("legal-triggers.yaml").write_text("# my edits\n")
    again = runner.invoke(main, ["init", "legal-triggers"])
    assert again.exit_code == 1
    assert "--force" in again.output
    assert Path("legal-triggers.yaml").read_text() == "# my edits\n"
    forced = runner.invoke(main, ["init", "legal-triggers", "--force"])
    assert forced.exit_code == 0
    assert Path("legal-triggers.yaml").read_text() != "# my edits\n"


def test_init_unknown_pack_lists_bundled(tmp_path: Path) -> None:
    res = CliRunner().invoke(main, ["init", "nope", "--dir", str(tmp_path)])
    assert res.exit_code == 2
    assert "legal-triggers" in res.output and "outbound-claims" in res.output


@pytest.mark.parametrize("name", ["legal-triggers", "outbound-claims"])
def test_bundled_samples_match_repo_files(name: str) -> None:
    root = Path(__file__).resolve().parents[1]
    assert bundled_dataset(name) == (root / "evals" / name / "dataset.jsonl").resolve() or (
        bundled_dataset(name).read_bytes()  # type: ignore[union-attr]
        == (root / "evals" / name / "dataset.jsonl").read_bytes()
    )
