"""Reference packs, sample datasets and keyword baselines shipped with the package."""

from __future__ import annotations

import re
from pathlib import Path

_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_HERE = Path(__file__).resolve()


def _first_dir(name: str) -> Path | None:
    # Installed wheel: dutygate/<name>/. Source checkout: <repo>/<name>/.
    for candidate in (_HERE.parent / name, _HERE.parents[2] / name):
        if candidate.is_dir():
            return candidate
    return None


def packs_dir() -> Path | None:
    return _first_dir("packs")


def bundled_packs() -> list[str]:
    """Names of the reference packs shipped with the package (loadable by name)."""
    directory = packs_dir()
    return sorted(p.stem for p in directory.glob("*.yaml")) if directory else []


def bundled_pack(name: str) -> Path | None:
    directory = packs_dir()
    if directory is None or not _NAME.fullmatch(name):
        return None
    path = directory / f"{name}.yaml"
    return path if path.is_file() else None


def _eval_file(name: str, filename: str) -> Path | None:
    directory = _first_dir("evals")
    if directory is None or not _NAME.fullmatch(name):
        return None
    path = directory / name / filename
    return path if path.is_file() else None


def bundled_dataset(name: str) -> Path | None:
    """The sample labeled dataset for a bundled pack, if there is one."""
    return _eval_file(name, "dataset.jsonl")


def bundled_keywords(name: str) -> Path | None:
    """The keyword baseline for a bundled pack, if there is one."""
    return _eval_file(name, "keywords.yaml")
