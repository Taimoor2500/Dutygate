from __future__ import annotations

from typing import Literal

ErrorCode = Literal[
    "backend_timeout",
    "backend_unavailable",
    "backend_auth",
    "backend_rejected",
    "malformed_response",
    "message_too_long",
    "internal_error",
]


class DutyGateError(Exception):
    """Base class for every error this package raises."""


class PackError(DutyGateError):
    """A policy pack (or a file derived from one) is invalid."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__("invalid policy pack:\n  - " + "\n  - ".join(self.errors))


class DatasetError(DutyGateError):
    """An evaluation dataset is invalid."""


class ConfigError(DutyGateError):
    """Runtime configuration (usually an environment variable) is missing or invalid."""


class BackendError(DutyGateError):
    """A backend could not produce answers. The engine turns this into an error decision."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        self.code: ErrorCode = code
        self.message = message
        super().__init__(f"{code}: {message}")
