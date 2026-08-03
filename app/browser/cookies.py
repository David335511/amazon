"""Cookie management with persistence.

Stores and restores browser cookies to/from disk so sessions survive process
restarts. Cookies are stored per-domain group in a single JSON file using
Playwright's storage-state format (a list of {name, value, domain, path, ...}
dicts).

Design decisions:
- Playwright already round-trips cookies via context storage_state / add_cookies,
  so this manager is a thin, safe wrapper around those primitives plus disk IO.
- A single atomic JSON write prevents corruption from concurrent writes.
- Cookie stores are keyed by a logical name (e.g. "walmart-web") so suppliers
  keep isolated cookie jars.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from app.browser.errors import CookieStoreError

logger = logging.getLogger(__name__)


class CookieManager:
    """Persists and restores cookies for browser contexts."""

    def __init__(self, cookie_file: str = "browser_data/cookies.json") -> None:
        self._cookie_file = Path(cookie_file)
        self._lock_file = self._cookie_file.with_suffix(".lock")

    # ── Storage state (Playwright) ──────────────────────────

    def save(self, name: str, cookies: list[dict[str, Any]]) -> None:
        """Persist a list of cookies under a named key.

        Args:
            name: Logical cookie-jar name.
            cookies: Cookie dicts in Playwright format.

        Raises:
            CookieStoreError: If the store cannot be written.
        """
        try:
            store = self._read_store()
            store[name] = [dict(c) for c in cookies]
            self._write_store(store)
        except CookieStoreError:
            raise
        except Exception as exc:
            raise CookieStoreError(f"Failed to save cookies for '{name}': {exc}") from exc

    def load(self, name: str) -> list[dict[str, Any]]:
        """Load the cookies previously saved under a named key.

        Returns:
            A list of cookie dicts (empty list if none exist).

        Raises:
            CookieStoreError: If the store cannot be read.
        """
        try:
            store = self._read_store()
            return list(store.get(name, []))
        except CookieStoreError:
            raise
        except Exception as exc:
            raise CookieStoreError(f"Failed to load cookies for '{name}': {exc}") from exc

    def delete(self, name: str) -> None:
        """Delete a named cookie jar."""
        try:
            store = self._read_store()
            store.pop(name, None)
            self._write_store(store)
        except Exception as exc:
            raise CookieStoreError(f"Failed to delete cookies for '{name}': {exc}") from exc

    def list_names(self) -> list[str]:
        """List all named cookie jars that exist in the store."""
        try:
            return list(self._read_store().keys())
        except CookieStoreError:
            return []
        except Exception:
            return []

    def clear_all(self) -> None:
        """Remove the entire cookie store file."""
        try:
            if self._cookie_file.exists():
                self._cookie_file.unlink()
        except Exception as exc:
            raise CookieStoreError(f"Failed to clear cookie store: {exc}") from exc

    # ── Browser integration ─────────────────────────────────

    async def persist_from_context(self, name: str, context: Any) -> None:
        """Save the cookies currently held by a Playwright browser context.

        Args:
            name: Logical cookie-jar name.
            context: A Playwright `BrowserContext`.
        """
        try:
            cookies = await context.cookies()
        except Exception as exc:
            raise CookieStoreError(f"Failed to read cookies from context: {exc}") from exc
        self.save(name, [dict(c) for c in cookies])

    async def apply_to_context(self, name: str, context: Any) -> int:
        """Restore a saved cookie jar onto a Playwright context.

        Args:
            name: Logical cookie-jar name.
            context: A Playwright `BrowserContext`.

        Returns:
            The number of cookies applied.
        """
        cookies = self.load(name)
        if cookies:
            try:
                await context.add_cookies(cookies)
            except Exception as exc:
                raise CookieStoreError(f"Failed to apply cookies to context: {exc}") from exc
        return len(cookies)

    # ── Internal ────────────────────────────────────────────

    def _read_store(self) -> dict[str, list[dict[str, Any]]]:
        if not self._cookie_file.exists():
            return {}
        with open(self._cookie_file, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return {}
        return {k: (v if isinstance(v, list) else []) for k, v in data.items()}

    def _write_store(self, store: dict[str, list[dict[str, Any]]]) -> None:
        self._cookie_file.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: write to a temp file in the same directory then rename.
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self._cookie_file.parent),
            prefix="cookies",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(store, fh, indent=2)
            os.replace(tmp_path, self._cookie_file)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise
