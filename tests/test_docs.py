"""Keep the docs honest: the quickstart runs, the spec covers the schema, versions agree."""

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

from dutygate import __version__
from dutygate.schema import Context, Criteria, Defaults, Limits, Pack, Question, Rule

ROOT = Path(__file__).resolve().parents[1]
BIN = Path(sys.executable).parent


def quickstart_commands() -> list[str]:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Quickstart", 1)[1]
    block = re.search(r"```console\n(.*?)```", section, re.S)
    assert block, "README quickstart needs a ```console block"
    lines, current = [], ""
    for raw in block.group(1).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        current += line.rstrip("\\").strip() + " "
        if not line.endswith("\\"):
            lines.append(current.strip())
            current = ""
    return [c for c in lines if not c.startswith(("pip ", "uv pip ", "git clone", "cd "))]


def test_readme_quickstart_runs() -> None:
    commands = quickstart_commands()
    assert any("validate" in c for c in commands) and any("run" in c for c in commands)
    env = {**os.environ, "PATH": f"{BIN}{os.pathsep}{os.environ['PATH']}"}
    env.pop("TYPESAFE_API_KEY", None)
    for command in commands:
        args = shlex.split(command)
        res = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
        assert res.returncode == 0, f"{command}\n{res.stdout}\n{res.stderr}"


def test_spec_mentions_every_pack_field() -> None:
    spec = (ROOT / "SPEC.md").read_text(encoding="utf-8")
    for model in (Pack, Defaults, Limits, Context, Question, Criteria, Rule):
        for field in model.model_fields:
            assert f"`{field}`" in spec, f"SPEC.md does not document {model.__name__}.{field}"


def test_versions_agree() -> None:
    pkg = json.loads((ROOT / "clients" / "typescript" / "package.json").read_text())
    assert pkg["version"] == __version__
    assert f"## [{__version__}]" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_community_files_exist() -> None:
    for name in [
        "LICENSE",
        "SECURITY.md",
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
        "CHANGELOG.md",
        "docs/integration.md",
        "docs/privacy.md",
        "docs/labeling.md",
        "docs/sidecar.md",
        "docs/adapters.md",
    ]:
        assert (ROOT / name).is_file(), name
