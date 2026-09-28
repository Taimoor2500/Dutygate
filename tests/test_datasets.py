"""Sanity checks on the bundled evaluation datasets and keyword baselines."""

from collections import Counter
from pathlib import Path

import pytest
from click.testing import CliRunner

from dutygate import KeywordBackend, load_policy
from dutygate.cli import main
from dutygate.evaluation import load_dataset

ROOT = Path(__file__).resolve().parents[1]

DATASETS = {
    "legal-triggers": {
        "min_rows": 150,
        "min_tags": {
            "multi-flag": 5,
            "near-miss": 15,
            "adversarial": 10,
            "typo": 5,
            "slang": 5,
            "implicit": 10,
            "non-english": 25,
        },
        "min_langs": {"es": 5, "fr": 5, "de": 5, "ar": 5, "ur": 5},
    },
    "outbound-claims": {
        "min_rows": 60,
        "min_tags": {"multi-flag": 5, "near-miss": 10, "implicit": 5},
        "min_langs": {},
    },
}


@pytest.mark.parametrize("name", sorted(DATASETS))
def test_dataset_is_valid_and_broad(name: str) -> None:
    spec = DATASETS[name]
    pack = load_policy(ROOT / "packs" / f"{name}.yaml")
    rows = load_dataset(ROOT / "evals" / name / "dataset.jsonl")
    assert len(rows) >= spec["min_rows"]  # type: ignore[operator]
    assert {lbl for r in rows for lbl in r.labels} <= set(pack.categories)
    assert {lbl for r in rows for lbl in r.labels} == set(pack.categories)  # every category used
    tags = Counter(t for r in rows for t in r.tags)
    for tag, n in spec["min_tags"].items():  # type: ignore[attr-defined]
        assert tags[tag] >= n, f"{tag}: {tags[tag]} < {n}"
    langs = Counter(r.lang for r in rows)
    for lang, n in spec["min_langs"].items():  # type: ignore[attr-defined]
        assert langs[lang] >= n, f"{lang}: {langs[lang]} < {n}"
    share = sum(r.positive for r in rows) / len(rows)
    assert 0.5 <= share <= 0.75


@pytest.mark.parametrize("name", sorted(DATASETS))
def test_keywords_file_loads(name: str) -> None:
    pack = load_policy(ROOT / "packs" / f"{name}.yaml")
    KeywordBackend.from_file(ROOT / "evals" / name / "keywords.yaml", pack)


@pytest.mark.parametrize("name", sorted(DATASETS))
def test_keyword_baseline_eval_runs(name: str) -> None:
    res = CliRunner().invoke(
        main,
        [
            "eval",
            str(ROOT / "packs" / f"{name}.yaml"),
            str(ROOT / "evals" / name / "dataset.jsonl"),
            "--backend",
            "keyword",
            "--keywords",
            str(ROOT / "evals" / name / "keywords.yaml"),
        ],
    )
    assert res.exit_code == 0, res.output
    assert "| caught" in res.stdout
