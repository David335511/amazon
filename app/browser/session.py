"""Session persistence and isolation.

A "session" is a named, persisted browser context. Sessions capture the full
storage state (cookies, localStorage, origins) to disk so that logged-in or
customized states survive restarts, and so different suppliers/tasks keep fully
isolated browser profiles.

SessionManager creates isolated Playwright contexts from a saved storage state,
and persists state back to disk. It coordinates with CookieManager (for cookie
jars) and ProxyManager (for per-session proxies).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from app.browser.errors import SessionPersistError

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages named persistent browser sessions.

    Args:
        session_dir: Directory where session storage-state files are kept.
    """

    def __init__(self, session_dir: str = "browser_data/sessions") -> None:
        self._dir = Path(session_dir)

    # ── Storage state persistence ───────────────────────────

    def load_state(self, name: str) -> dict[str, Any]:
        """Load the storage-state dict for a named session.

        Returns:
            A Playwright storage-state dict (``{}`` if the session has no
            saved state yet).
        """
        path = self._session_file(name)
        if not path.exists():
            return {}
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            raise SessionPersistError(f"Failed to load session '{name}': {exc}") from exc

    def save_state(self, name: str, state: dict[str, Any]) -> None:
        """Persist a storage-state dict for a named session."""
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._session_file(name)
        # Atomic write to avoid corruption from concurrent writes.
        fd, tmp = tempfile.mkstemp(dir=str(self._dir), prefix=f"{name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(state, fh, indent=2)
            os.replace(tmp, path)
        except Exception as exc:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise SessionPersistError(f"Failed to save session '{name}': {exc}") from exc

    async def persist_context(self, name: str, context: Any) -> None:
        """Capture a Playwright context's storage state to disk.

        Args:
            name: Session name.
            context: A Playwright `BrowserContext`.
        """
        try:
            state = await context.storage_state()
        except Exception as exc:
            raise SessionPersistError(f"Failed to capture state for '{name}': {exc}") from exc
        self.save_state(name, state)

    async def apply_to_context(self, name: str, context: Any) -> None:
        """Create/add the saved session state onto an existing context.

        Playwright contexts are immutable after creation for storage_state, so
        this applies cookies only (the practical, high-value subset).
        """
        state = self.load_state(name)
        cookies = state.get("cookies", [])
        if cookies:
            try:
                await context.add_cookies(cookies)
            except Exception as exc:
                raise SessionPersistError(f"Failed to apply session '{name}': {exc}") from exc

    def session_exists(self, name: str) -> bool:
        """Whether a named session has persisted state."""
        return self._session_file(name).exists()

    def list_sessions(self) -> list[str]:
        """List all persisted session names."""
        if not self._dir.exists():
            return []
        return [p.stem for p in self._dir.glob("*.json") if p.stem]

    def delete(self, name: str) -> None:
        """Delete a persisted session."""
        path = self._session_file(name)
        if path.exists():
            try:
                path.unlink()
            except Exception as exc:
                raise SessionPersistError(f"Failed to delete session '{name}': {exc}") from exc

    def _session_file(self, name: str) -> Path:
        # Sanitize the name to avoid path traversal.
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name) or "default"
        return self._dir / f"{safe}.json"
