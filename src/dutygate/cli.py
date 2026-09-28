"""`dutygate` command line: validate packs, judge messages, run evals, serve the sidecar."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Literal, NoReturn

import click

from ._version import __version__
from .backends.base import Backend
from .bundled import bundled_dataset, bundled_keywords, bundled_pack, bundled_packs
from .errors import ConfigError, PackError
from .schema import REDACTION_FILE_ENV, Pack, load_policy, load_policy_with_warnings, load_redaction

BackendKind = Literal["jev", "replay", "keyword"]
EXIT_FOR_ACTION = {"continue": 0, "route": 10, "review": 11}

pack_argument = click.argument("pack", type=click.Path(path_type=Path))
backend_option = click.option(
    "--backend",
    "backend_kind",
    type=click.Choice(["jev", "replay", "keyword"]),
    default="jev",
    show_default=True,
    help="jev calls TypeSafe; replay answers from fixtures; keyword is the eval baseline.",
)
fixtures_option = click.option(
    "--fixtures",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Replay fixtures: an answers .jsonl file or conformance/cases.json.",
)
keywords_option = click.option(
    "--keywords",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Keyword baseline file (question id -> list of regexes).",
)


def fail_pack(exc: PackError) -> NoReturn:
    for err in exc.errors:
        click.echo(f"error: {err}", err=True)
    sys.exit(1)


def load_pack_or_exit(path: Path) -> Pack:
    try:
        return load_policy(path)
    except PackError as exc:
        fail_pack(exc)


def extra_redaction_note() -> str:
    source = os.environ.get(REDACTION_FILE_ENV)
    if not source:
        return ""
    count = len(load_redaction(source))
    return f", {count} extra redaction rule{'s' if count != 1 else ''} from {source}"


def is_conformance_file(path: Path) -> bool:
    if path.suffix != ".json":
        return False
    try:
        return "cases" in json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False


def make_backend(
    kind: BackendKind, pack: Pack, *, fixtures: Path | None, keywords: Path | None
) -> Backend:
    """Build a backend from CLI options. Raises click.UsageError for missing configuration."""
    if kind == "replay":
        from .backends.replay import ReplayBackend

        if fixtures is None:
            raise click.UsageError("--backend replay needs --fixtures")
        if is_conformance_file(fixtures):
            return ReplayBackend.from_conformance(fixtures, pack)
        return ReplayBackend.from_file(fixtures, pack)
    if kind == "keyword":
        from .backends.keyword import KeywordBackend

        if keywords is None:
            keywords = bundled_keywords(pack.name)
        if keywords is None:
            raise click.UsageError(
                f"--backend keyword needs --keywords (pack '{pack.name}' has no bundled keywords)"
            )
        return KeywordBackend.from_file(keywords, pack)
    from .backends.jev import TypeSafeJevBackend

    try:
        return TypeSafeJevBackend.from_env()
    except ConfigError as exc:
        raise click.UsageError(str(exc)) from None


@click.group()
@click.version_option(__version__, prog_name="dutygate")
def main() -> None:
    """DutyGate: flag legal and compliance triggers before a chatbot replies."""


@main.command()
@click.argument("packs", nargs=-1, required=True, type=click.Path(path_type=Path))
def validate(packs: tuple[Path, ...]) -> None:
    """Check one or more policy packs. Exits 1 if any pack is invalid."""
    failed = False
    for path in packs:
        try:
            pack, warnings = load_policy_with_warnings(path)
        except PackError as exc:
            failed = True
            click.echo(f"{path}: invalid", err=True)
            for err in exc.errors:
                click.echo(f"  error: {err}", err=True)
            continue
        for warning in warnings:
            click.echo(f"{path}: warning: {warning}", err=True)
        extra = extra_redaction_note()
        click.echo(f"{path}: ok ({pack.name} {pack.version}, {len(pack.rules)} rules{extra})")
    if failed:
        sys.exit(1)


@main.command()
@pack_argument
@click.option("--state", "message", required=True, help="The message to judge, or - for stdin.")
@backend_option
@fixtures_option
@keywords_option
@click.option("--conversation-id", default=None)
@click.option("--channel", default=None)
@click.option("--recent", "recent", multiple=True, help="An earlier message (repeatable).")
@click.option(
    "--exit-code",
    "use_exit_code",
    is_flag=True,
    help="Exit 0 for continue, 10 for route, 11 for review.",
)
def run(
    pack: Path,
    message: str,
    backend_kind: BackendKind,
    fixtures: Path | None,
    keywords: Path | None,
    conversation_id: str | None,
    channel: str | None,
    recent: tuple[str, ...],
    use_exit_code: bool,
) -> None:
    """Judge one message and print the decision as JSON."""
    from .gate import Gate

    loaded = load_pack_or_exit(pack)
    if message == "-":
        message = sys.stdin.read().rstrip("\n")
    try:
        backend = make_backend(backend_kind, loaded, fixtures=fixtures, keywords=keywords)
    except PackError as exc:
        fail_pack(exc)
    with Gate(loaded, backend) as gate:
        decision = gate.check(
            message,
            conversation_id=conversation_id,
            channel=channel,
            recent_messages=list(recent) or None,
        )
    click.echo(decision.to_json())
    if use_exit_code:
        sys.exit(EXIT_FOR_ACTION[decision.action])


def _per_pack(values: tuple[Path, ...], n: int, flag: str) -> list[Path | None]:
    if not values:
        return [None] * n
    if len(values) == 1:
        return [values[0]] * n
    if len(values) == n:
        return list(values)
    raise click.UsageError(f"pass {flag} once (shared) or once per pack ({n})")


@main.command()
@click.argument("packs", nargs=-1, required=True, type=click.Path(path_type=Path))
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8080, show_default=True, type=click.IntRange(1, 65535))
@backend_option
@click.option(
    "--fixtures",
    "fixtures_list",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Replay fixtures (once, or once per pack).",
)
@click.option(
    "--keywords",
    "keywords_list",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Keyword files (once, or once per pack).",
)
@click.option(
    "--audit-log",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Append a JSONL audit record for every decision.",
)
@click.option(
    "--audit-include-message",
    is_flag=True,
    help="Also store message text in the audit log (off by default).",
)
@click.option(
    "--insecure-no-auth",
    is_flag=True,
    help="Disable API keys. Only allowed when binding to 127.0.0.1.",
)
@click.option(
    "--log-level",
    default="info",
    show_default=True,
    type=click.Choice(["debug", "info", "warning", "error"]),
)
def serve(
    packs: tuple[Path, ...],
    host: str,
    port: int,
    backend_kind: BackendKind,
    fixtures_list: tuple[Path, ...],
    keywords_list: tuple[Path, ...],
    audit_log: Path | None,
    audit_include_message: bool,
    insecure_no_auth: bool,
    log_level: str,
) -> None:
    """Run the HTTP sidecar. The first pack answers POST /v1/gate."""
    try:
        from .server import ServerConfig, create_app
        from .server import run as server_run
    except ImportError as exc:  # pragma: no cover - depends on installed extras
        raise click.UsageError(
            f"the sidecar needs the server extra: pip install 'dutygate[server]' ({exc})"
        ) from None
    from .gate import Gate

    if insecure_no_auth and host != "127.0.0.1":
        raise click.UsageError("--insecure-no-auth only binds to 127.0.0.1")
    keys = server_run.keys_from_env()
    if not keys and not insecure_no_auth:
        raise click.UsageError(
            "set DUTYGATE_SIDECAR_KEYS (comma-separated API keys) or pass --insecure-no-auth"
        )
    loaded = [load_pack_or_exit(p) for p in packs]
    fixtures = _per_pack(fixtures_list, len(loaded), "--fixtures")
    keywords = _per_pack(keywords_list, len(loaded), "--keywords")
    gates = []
    try:
        for pack, fx, kw in zip(loaded, fixtures, keywords, strict=True):
            gates.append(Gate(pack, make_backend(backend_kind, pack, fixtures=fx, keywords=kw)))
    except PackError as exc:
        fail_pack(exc)
    config = ServerConfig(
        api_keys=keys,
        insecure_no_auth=insecure_no_auth,
        audit_log=audit_log,
        audit_include_message=audit_include_message,
    )
    try:
        app = create_app(gates, config)
    except (ConfigError, ValueError) as exc:
        raise click.UsageError(str(exc)) from None
    server_run.run_uvicorn(app, host, port, log_level)


@main.command()
@click.argument("name")
@click.option(
    "--dir",
    "directory",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("."),
    show_default=True,
    help="Where to write the files.",
)
@click.option("--force", is_flag=True, help="Overwrite existing files.")
def init(name: str, directory: Path, force: bool) -> None:
    """Copy a bundled pack, its sample dataset and its keywords here, to customize."""
    import shutil

    source = bundled_pack(name)
    if source is None:
        raise click.UsageError(
            f"unknown pack '{name}'; bundled packs: {', '.join(bundled_packs())}"
        )
    targets = {directory / f"{name}.yaml": source}
    dataset, keywords = bundled_dataset(name), bundled_keywords(name)
    if dataset is not None:
        targets[directory / f"{name}.dataset.jsonl"] = dataset
    if keywords is not None:
        targets[directory / f"{name}.keywords.yaml"] = keywords
    existing = [str(t) for t in targets if t.exists()]
    if existing and not force:
        click.echo(
            f"error: already exists: {', '.join(existing)} (use --force to overwrite)", err=True
        )
        sys.exit(1)
    directory.mkdir(parents=True, exist_ok=True)
    for target, src in targets.items():
        shutil.copyfile(src, target)
        click.echo(f"created {target}")
    pack_file = directory / f"{name}.yaml"
    click.echo("\nEdit the pack (questions, thresholds, queues), change its `name`, then:")
    click.echo(f"  dutygate validate {pack_file}")
    if dataset is not None and keywords is not None:
        click.echo(
            f"  dutygate eval {pack_file} {directory / f'{name}.dataset.jsonl'} "
            f"--backend keyword --keywords {directory / f'{name}.keywords.yaml'}"
        )


@main.command("eval")
@pack_argument
@click.argument(
    "dataset", required=False, type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
@backend_option
@fixtures_option
@keywords_option
@click.option(
    "--replay",
    "replay_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Re-score answers saved with --save-answers (implies --backend replay).",
)
@click.option("--save-answers", type=click.Path(dir_okay=False, path_type=Path))
@click.option(
    "--baseline",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Keywords file for a side-by-side keyword baseline.",
)
@click.option("--report", type=click.Path(dir_okay=False, path_type=Path), help="Write JSON.")
@click.option("--fail-under", default=None, help='e.g. "caught=0.95,false_review=0.10"')
@click.option("--sweep", "do_sweep", is_flag=True, help="Per-rule threshold sweep on answers.")
@click.option("--concurrency", default=4, show_default=True, type=click.IntRange(min=1))
def eval_command(
    pack: Path,
    dataset: Path | None,
    backend_kind: BackendKind,
    fixtures: Path | None,
    keywords: Path | None,
    replay_path: Path | None,
    save_answers: Path | None,
    baseline: Path | None,
    report: Path | None,
    fail_under: str | None,
    do_sweep: bool,
    concurrency: int,
) -> None:
    """Score a backend on a labeled JSONL dataset.

    DATASET defaults to the sample dataset shipped with a bundled pack.
    """
    from .backends.keyword import KeywordBackend
    from .errors import DatasetError
    from .evaluation import (
        check_fail_under,
        compute_metrics,
        load_dataset,
        render_markdown,
        to_json,
    )
    from .evaluation import run as run_eval
    from .evaluation.sweep import load_answers, pareto, sweep

    loaded = load_pack_or_exit(pack)
    if dataset is None:
        dataset = bundled_dataset(loaded.name)
        if dataset is None:
            raise click.UsageError(
                f"give a DATASET: pack '{loaded.name}' has no bundled sample dataset"
            )
    if replay_path is not None:
        backend_kind, fixtures = "replay", replay_path
    answers_path = replay_path or save_answers
    if do_sweep and answers_path is None:
        raise click.UsageError("--sweep needs saved answers: pass --replay or --save-answers")
    try:
        rows = load_dataset(dataset)
    except DatasetError as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)
    unknown = sorted({lbl for r in rows for lbl in r.labels} - set(loaded.categories))
    if unknown:
        click.echo(
            f"error: dataset labels not in pack {loaded.name}: {', '.join(unknown)}", err=True
        )
        sys.exit(1)
    if fail_under is not None:
        try:
            check_fail_under(compute_metrics([], loaded.categories), fail_under)
        except ValueError as exc:
            raise click.UsageError(str(exc)) from None

    try:
        backend = make_backend(backend_kind, loaded, fixtures=fixtures, keywords=keywords)
        base_backend = KeywordBackend.from_file(baseline, loaded) if baseline else None
    except PackError as exc:
        fail_pack(exc)
    try:
        results = run_eval(
            loaded, rows, backend, concurrency=concurrency, save_answers=save_answers
        )
    finally:
        backend.close()
    metrics = compute_metrics(results, loaded.categories)
    base_metrics = None
    if base_backend is not None:
        base_metrics = compute_metrics(run_eval(loaded, rows, base_backend), loaded.categories)

    click.echo(
        render_markdown(metrics, base_metrics, name=backend.name, baseline_name="keyword baseline")
    )
    if do_sweep and answers_path is not None:
        try:
            points = sweep(loaded, rows, load_answers(answers_path, loaded))
        except PackError as exc:
            fail_pack(exc)
        click.echo("Threshold sweep (Pareto front: recall vs false review, per rule):\n")
        for rule in loaded.rules:
            t = loaded.thresholds_for(rule)
            click.echo(f"{rule.id} (now low={t.low:g} high={t.high:g})")
            for p in pareto([p for p in points if p.rule_id == rule.id])[:8]:
                click.echo(
                    f"  low={p.low:<4g} high={p.high:<4g} recall={p.recall:.2f} "
                    f"routed={p.route_recall:.2f} false_review={p.false_review:.2f}"
                )
        click.echo("")

    failures = check_fail_under(metrics, fail_under) if fail_under else []
    if report is not None:
        data = to_json(metrics, base_metrics)
        data["fail_under"] = failures
        data["pack"] = {"name": loaded.name, "version": loaded.version}
        data["backend"] = backend.name
        report.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    for failure in failures:
        click.echo(f"fail-under: {failure}", err=True)
    if failures:
        sys.exit(1)
