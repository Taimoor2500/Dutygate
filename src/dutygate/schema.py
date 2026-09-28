"""Policy pack models and loading. The normative format is described in SPEC.md."""

from __future__ import annotations

import hashlib
import json
from functools import cached_property
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .bundled import bundled_pack, bundled_packs
from .decision import Action, Priority
from .errors import PackError

QUESTION_ID = r"^[a-z][a-z0-9_]{0,63}$"
RULE_ID = r"^[a-z0-9][a-z0-9-]{0,63}$"
SEMVER = r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"

PRIORITY_RANK: dict[str, int] = {"urgent": 0, "high": 1, "normal": 2, "low": 3}

Probability = Annotated[float, Field(ge=0.0, le=1.0)]
NonEmptyStr = Annotated[str, Field(min_length=1)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Thresholds(_Model):
    low: Probability
    high: Probability

    @model_validator(mode="after")
    def _ordered(self) -> Thresholds:
        if self.low > self.high:
            raise ValueError(f"low ({self.low}) must be <= high ({self.high})")
        return self


class Defaults(_Model):
    thresholds: Thresholds = Thresholds(low=0.2, high=0.5)
    on_error: Action = "review"


class Limits(_Model):
    max_message_chars: Annotated[int, Field(ge=1)] = 8000


class Context(_Model):
    max_recent_messages: Annotated[int, Field(ge=0, le=50)] = 0


class RedactionRule(_Model):
    name: Annotated[str, Field(pattern=QUESTION_ID)]
    pattern: NonEmptyStr
    replacement: str | None = None
    luhn: bool = False


class Criteria(_Model):
    true: NonEmptyStr
    false: NonEmptyStr

    @model_validator(mode="before")
    @classmethod
    def _yaml_bool_keys(cls, data: Any) -> Any:
        # YAML 1.1 turns bare `true:` / `false:` keys into booleans.
        if isinstance(data, dict):
            return {
                ("true" if k is True else "false" if k is False else k): v for k, v in data.items()
            }
        return data


class Question(_Model):
    id: Annotated[str, Field(pattern=QUESTION_ID)]
    instructions: NonEmptyStr
    criteria: Criteria | None = None


class Rule(_Model):
    id: Annotated[str, Field(pattern=RULE_ID)]
    category: Annotated[str, Field(pattern=QUESTION_ID)]
    match: Literal["any", "all"] = "any"
    questions: Annotated[tuple[str, ...], Field(min_length=1)]
    queue: NonEmptyStr
    priority: Priority
    thresholds: Thresholds | None = None


class Pack(_Model):
    model_config = ConfigDict(extra="forbid", frozen=True, ignored_types=(cached_property,))

    schema_version: Literal[1]
    name: Annotated[str, Field(pattern=RULE_ID)]
    version: Annotated[str, Field(pattern=SEMVER)]
    description: str = ""
    state_field: Annotated[str, Field(pattern=QUESTION_ID)] = "customer_message"
    defaults: Defaults = Defaults()
    limits: Limits = Limits()
    context: Context = Context()
    redaction: tuple[RedactionRule, ...] = ()
    questions: Annotated[tuple[Question, ...], Field(min_length=1)]
    rules: Annotated[tuple[Rule, ...], Field(min_length=1)]

    def question(self, qid: str) -> Question:
        for q in self.questions:
            if q.id == qid:
                return q
        raise KeyError(qid)

    def thresholds_for(self, rule: Rule) -> Thresholds:
        return rule.thresholds or self.defaults.thresholds

    @property
    def categories(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(r.category for r in self.rules))

    @cached_property
    def questions_digest(self) -> str:
        items = sorted(
            (
                {
                    "id": q.id,
                    "instructions": q.instructions,
                    "criteria": q.criteria.model_dump() if q.criteria else None,
                }
                for q in self.questions
            ),
            key=lambda item: str(item["id"]),
        )
        blob = json.dumps(items, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _format_validation_error(exc: ValidationError) -> list[str]:
    out = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "<pack>"
        msg = err["msg"]
        value = err.get("input")
        if err["type"] != "extra_forbidden" and isinstance(value, (str, int, float, bool)):
            msg = f"{msg} (got {value!r})"
        out.append(f"{loc}: {msg}")
    return out


def _resolve(source: str | Path) -> Path:
    path = Path(source)
    if path.is_file():
        return path
    bundled = bundled_pack(str(source))
    if bundled is not None:
        return bundled
    available = ", ".join(bundled_packs()) or "none"
    raise PackError([f"pack file not found: {path} (bundled packs: {available})"])


def _read_source(source: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(source, dict):
        return source
    path = _resolve(source)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PackError([f"{path}: invalid YAML: {exc}"]) from exc
    if not isinstance(data, dict):
        raise PackError([f"{path}: a pack must be a YAML mapping at the top level"])
    return data


def load_policy_with_warnings(source: str | Path | dict[str, Any]) -> tuple[Pack, list[str]]:
    """Load and fully validate a pack. Raises PackError listing every problem found."""
    from .validate import semantic_errors, semantic_warnings

    data = _read_source(source)
    try:
        pack = Pack.model_validate(data)
    except ValidationError as exc:
        raise PackError(_format_validation_error(exc)) from None
    errors = semantic_errors(pack)
    if errors:
        raise PackError(errors)
    return pack, semantic_warnings(pack)


def load_policy(source: str | Path | dict[str, Any]) -> Pack:
    return load_policy_with_warnings(source)[0]
