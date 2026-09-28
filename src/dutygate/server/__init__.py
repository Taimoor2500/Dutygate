"""HTTP sidecar (`dutygate serve`). Requires the `server` extra."""

from .app import ServerConfig, create_app

__all__ = ["ServerConfig", "create_app"]
