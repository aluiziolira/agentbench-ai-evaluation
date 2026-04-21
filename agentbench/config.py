"""Shared runtime configuration helpers for AgentBench."""

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    """Environment-backed application settings."""

    mongodb_uri: str
    mongodb_db: str
    redis_url: str
    api_port: int
    api_host: str

    @property
    def api_base_url(self) -> str:
        """Client-safe API URL derived from host and port settings."""
        host = "localhost" if self.api_host in {"0.0.0.0", "::"} else self.api_host
        return f"http://{host}:{self.api_port}"


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default

    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def get_settings() -> Settings:
    """Load settings from environment with stable defaults."""
    return Settings(
        mongodb_uri=os.getenv("MONGODB_URI", "mongodb://localhost:27017"),
        mongodb_db=os.getenv("MONGODB_DB", "agentbench"),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379"),
        api_port=_get_int("API_PORT", 8000),
        api_host=os.getenv("API_HOST", "0.0.0.0"),
    )
