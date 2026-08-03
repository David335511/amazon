"""API authentication & security primitives.

Design decisions (Phase 0):
- **API-key auth** via the ``X-API-Key`` header. Keys are read from config
  (env ``API_KEYS``, comma-separated). This is a simple, free-tier-appropriate
  gate; a future JWT/OAuth layer can be added behind the same dependency seam
  without touching route code.
- **Public paths** (e.g. health probes) are exempt so orchestrators / keep-alive
  pingers never need a key.
- **Constant-time comparison** (``secrets.compare_digest``) to avoid timing
  side-channels.
- The whole ``/api/v1`` tree requires auth by default via the router dependency.
- Everything is gated by ``SecurityConfig.enabled`` — when disabled (local dev)
  the dependency is a no-op and no caller is affected.
"""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field, field_validator

DEFAULT_HEADER = "X-API-Key"
DEFAULT_PUBLIC_PATHS = ["/api/v1/health"]

_api_key_header = APIKeyHeader(name=DEFAULT_HEADER, auto_error=False)


class SecurityConfig(BaseModel):
    """API security configuration.

    Built from the ``security`` YAML block plus explicit env overrides applied
    in ``app.config.Settings.load()`` (``API_KEYS``, ``SECURITY_ENABLED``).
    Mutable so tests can enable it per-case.
    """

    enabled: bool = False
    api_keys: list[str] = Field(default_factory=list)
    header_name: str = DEFAULT_HEADER
    public_paths: list[str] = Field(default_factory=lambda: list(DEFAULT_PUBLIC_PATHS))

    @field_validator("api_keys", mode="before")
    @classmethod
    def _parse_api_keys(cls, v: Any) -> Any:
        """Accept a comma-separated string (env) or a list."""
        if isinstance(v, str):
            return [k.strip() for k in v.split(",") if k.strip()]
        return v


def _path_is_public(path: str, public_paths: list[str]) -> bool:
    """Return True if ``path`` matches one of the public path prefixes."""
    for prefix in public_paths:
        prefix = prefix.rstrip("/")
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


def authenticate(request: Request, api_key: str | None) -> bool:
    """Core authentication decision.

    Returns True if the request is authorized:
    - security disabled, OR
    - path is public, OR
    - a valid key was presented.
    """
    from app.config import settings

    cfg = getattr(settings, "security", SecurityConfig())
    if not cfg.enabled:
        return True
    if _path_is_public(request.url.path, cfg.public_paths):
        return True
    if not api_key or not cfg.api_keys:
        return False
    return any(secrets.compare_digest(api_key, k) for k in cfg.api_keys)


def require_api_key(
    request: Request,
    api_key: str | None = Depends(_api_key_header),
) -> None:
    """FastAPI dependency that enforces API-key authentication.

    Attach to the v1 router to protect the entire API surface at once.
    Returns 401 (or 403 for an invalid key) when authorization fails.
    """
    from app.config import settings

    cfg = getattr(settings, "security", SecurityConfig())
    if not cfg.enabled:
        return
    if _path_is_public(request.url.path, cfg.public_paths):
        return
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    if not any(secrets.compare_digest(api_key, k) for k in cfg.api_keys):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )
