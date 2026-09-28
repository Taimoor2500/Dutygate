"""DutyGate: flag legal and compliance triggers before a chatbot replies."""

from ._version import __version__
from .backends.base import Backend, BackendRequest, BackendResult
from .backends.jev import JevConfig, TypeSafeJevBackend
from .backends.keyword import KeywordBackend
from .backends.replay import ReplayBackend
from .bundled import bundled_packs
from .decision import Decision, ErrorInfo, Flag
from .engine import evaluate, evaluate_async
from .errors import BackendError, ConfigError, DutyGateError, PackError
from .gate import Gate
from .holding import DEFAULT_HOLDING_REPLY, default_holding_reply
from .schema import Pack, load_policy, load_policy_with_warnings

__all__ = [
    "DEFAULT_HOLDING_REPLY",
    "Backend",
    "BackendError",
    "BackendRequest",
    "BackendResult",
    "ConfigError",
    "Decision",
    "DutyGateError",
    "ErrorInfo",
    "Flag",
    "Gate",
    "JevConfig",
    "KeywordBackend",
    "Pack",
    "PackError",
    "ReplayBackend",
    "TypeSafeJevBackend",
    "__version__",
    "bundled_packs",
    "default_holding_reply",
    "evaluate",
    "evaluate_async",
    "load_policy",
    "load_policy_with_warnings",
]
