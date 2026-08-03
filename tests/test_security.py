"""Tests for Phase 0 API security (API-key auth + CORS hardening)."""

from __future__ import annotations

import pytest
from fastapi import Request
from httpx import AsyncClient

from app.config import settings
from app.core.security import (
    DEFAULT_PUBLIC_PATHS,
    SecurityConfig,
    _path_is_public,
    authenticate,
    require_api_key,
)


@pytest.fixture
def _security_enabled() -> None:
    """Enable API-key auth for the duration of a test, then restore."""
    saved = SecurityConfig.model_validate(settings.security.model_dump())
    settings.security.enabled = True
    settings.security.api_keys = ["test-key-1", "test-key-2"]
    yield
    settings.security.enabled = saved.enabled
    settings.security.api_keys = saved.api_keys
    settings.security.public_paths = saved.public_paths


# ── Unit: SecurityConfig ──────────────────────────────────────


def test_parse_comma_separated_api_keys() -> None:
    cfg = SecurityConfig(api_keys="key-a, key-b,key-c")
    assert cfg.api_keys == ["key-a", "key-b", "key-c"]


def test_parse_list_api_keys() -> None:
    cfg = SecurityConfig(api_keys=["one", "two"])
    assert cfg.api_keys == ["one", "two"]


def test_default_public_paths() -> None:
    cfg = SecurityConfig()
    assert cfg.public_paths == list(DEFAULT_PUBLIC_PATHS)
    assert cfg.enabled is False


# ── Unit: path matching ───────────────────────────────────────


def test_path_is_public_prefix_and_exact() -> None:
    paths = ["/api/v1/health"]
    assert _path_is_public("/api/v1/health", paths) is True
    assert _path_is_public("/api/v1/health/live", paths) is True
    assert _path_is_public("/api/v1/health/ready", paths) is True
    assert _path_is_public("/api/v1/products/", paths) is False
    assert _path_is_public("/api/v1/healthcare", paths) is False  # not a prefix match


# ── Integration: auth dependency ──────────────────────────────


async def _make_request(path: str) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "root_path": "",
        "headers": [(b"host", b"testserver")],
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_disabled_security_always_allows() -> None:
    settings.security.enabled = False
    req = await _make_request("/api/v1/products/")
    assert authenticate(req, api_key=None) is True
    require_api_key(req, api_key=None)


@pytest.mark.asyncio
async def test_public_path_allowed_without_key(_security_enabled: None) -> None:
    req = await _make_request("/api/v1/health/live")
    assert authenticate(req, api_key=None) is True
    require_api_key(req, api_key=None)


@pytest.mark.asyncio
async def test_missing_key_denied(_security_enabled: None) -> None:
    req = await _make_request("/api/v1/products/")
    assert authenticate(req, api_key=None) is False


@pytest.mark.asyncio
async def test_invalid_key_denied(_security_enabled: None) -> None:
    req = await _make_request("/api/v1/products/")
    assert authenticate(req, api_key="wrong-key") is False


@pytest.mark.asyncio
async def test_valid_key_allowed(_security_enabled: None) -> None:
    req = await _make_request("/api/v1/products/")
    assert authenticate(req, api_key="test-key-1") is True
    assert authenticate(req, api_key="test-key-2") is True


# ── Integration: over the HTTP API ────────────────────────────


@pytest.mark.asyncio
async def test_api_requires_key(client: AsyncClient, _security_enabled: None) -> None:
    # No key → 401
    resp = await client.get("/api/v1/products/")
    assert resp.status_code == 401

    # Invalid key → 403
    resp = await client.get("/api/v1/products/", headers={"X-API-Key": "nope"})
    assert resp.status_code == 403

    # Valid key → allowed
    resp = await client.get("/api/v1/products/", headers={"X-API-Key": "test-key-1"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_health_probe_is_public(client: AsyncClient, _security_enabled: None) -> None:
    resp = await client.get("/api/v1/health/live")
    assert resp.status_code == 200
    assert resp.json()["status"] == "alive"


@pytest.mark.asyncio
async def test_default_disabled_requires_no_key(client: AsyncClient) -> None:
    # With security disabled (default), endpoints are open.
    settings.security.enabled = False
    resp = await client.get("/api/v1/health/live")
    assert resp.status_code == 200
