"""Tests for the browser automation framework.

These tests exercise the framework WITHOUT a real browser (Playwright may not
be installed in CI). Browser-facing services are tested with fakes; pure logic
(rate limiter, retries, fingerprint, cookies, sessions, proxies, interception,
captcha detection) is tested directly.
"""

from __future__ import annotations

import time

import pytest

from app.browser.captcha import CaptchaDetector
from app.browser.config import (
    BrowserAutomationConfig,
    BrowserConfig,
    BrowserProxyConfig,
    FingerprintConfig,
    ProxyConfig,
)
from app.browser.cookies import CookieManager
from app.browser.crawler import Crawler
from app.browser.errors import (
    BrowserPoolTimeoutError,
    BrowserRateLimitError,
    BrowserTimeoutError,
    ProxyError,
    ProxyExhaustedError,
)
from app.browser.fingerprint import FingerprintRandomizer
from app.browser.interceptors import RequestInterceptor
from app.browser.manager import BrowserManager
from app.browser.models import CrawlResult
from app.browser.pool import PagePool
from app.browser.proxy import ProxyManager
from app.browser.rate_limiter import RateLimiter
from app.browser.retry import retry_async
from app.browser.session import SessionManager

# ── Fakes (no real Playwright) ──────────────────────────────


class _FakeLocator:
    def __init__(self, count: int) -> None:
        self._count = count

    def count(self) -> int:
        return self._count


class _FakeResponse:
    def status(self) -> int:
        return 200


class _FakeContext:
    def __init__(
        self,
        cookies: list[dict] | None = None,
        page_factory=None,
    ) -> None:
        self._cookies = cookies or [{"name": "a", "value": "1", "domain": ".example.com"}]
        self._page_factory = page_factory or _FakePage

    async def cookies(self) -> list[dict]:
        return self._cookies

    async def add_cookies(self, cookies: list[dict]) -> None:
        self._cookies.extend(cookies)

    async def new_page(self) -> _FakePage:
        return self._page_factory()

    async def close(self) -> None:
        return None

    async def storage_state(self) -> dict:
        return {"cookies": self._cookies}


class _FakePage:
    def __init__(
        self,
        *,
        title: str = "Test",
        html: str = "<html><body>Hello</body></html>",
        text: str = "Hello",
        url: str = "https://example.com/p",
        selectors: set[str] | None = None,
    ) -> None:
        self.context = _FakeContext()
        self._title = title
        self._html = html
        self._text = text
        self._url = url
        self._selectors = selectors or set()

    async def goto(self, url: str, **kwargs) -> _FakeResponse:  # noqa: ARG002 - Playwright stub
        self._url = url
        return _FakeResponse()

    async def title(self) -> str:
        return self._title

    async def content(self) -> str:
        return self._html

    async def evaluate(self, expr: str) -> str:  # noqa: ARG002 - Playwright stub
        return self._text

    @property
    def url(self) -> str:
        return self._url

    def locator(self, selector: str) -> _FakeLocator:
        return _FakeLocator(1 if selector in self._selectors else 0)

    async def screenshot(self, **kwargs) -> bytes:  # noqa: ARG002 - Playwright stub
        return b"png-bytes"

    async def close(self) -> None:
        return None


class _FakeBrowserManager:
    """Duck-typed BrowserManager for Crawler/PagePool tests."""

    def __init__(self, *, page_factory=None, proxy_manager: ProxyManager | None = None) -> None:
        self.proxy_manager = proxy_manager or ProxyManager()
        self.config = BrowserConfig(
            request_delay_min_ms=0,
            request_delay_max_ms=0,
            max_pages=2,
        )
        self._page_factory = page_factory or _FakePage
        self._launched = True

    @property
    def is_available(self) -> bool:
        return self._launched

    async def launch(self) -> None:
        self._launched = True

    async def shutdown(self) -> None:
        self._launched = False

    async def new_context(self, **kwargs) -> _FakeContext:
        ctx = _FakeContext(page_factory=self._page_factory)
        state = kwargs.get("session_state")
        if state:
            await ctx.add_cookies(state.get("cookies") or [])
        return ctx


# ── Config ──────────────────────────────────────────────────


class TestConfig:
    def test_defaults(self) -> None:
        cfg = BrowserAutomationConfig()
        assert cfg.enabled is False
        assert cfg.browser.headless is True
        assert cfg.browser.max_pages == 8
        assert cfg.browser.navigation_timeout_ms == 30000

    def test_visible_overrides_headless(self) -> None:
        cfg = BrowserAutomationConfig(browser=BrowserConfig(headless=True, visible=True))
        manager = BrowserManager(cfg.browser)
        assert manager.headless is False

    def test_from_dict(self) -> None:
        cfg = BrowserAutomationConfig.model_validate(
            {"enabled": True, "browser": {"headless": False, "max_pages": 4}}
        )
        assert cfg.enabled is True
        assert cfg.browser.headless is False
        assert cfg.browser.max_pages == 4


# ── Rate limiter ────────────────────────────────────────────


class TestRateLimiter:
    async def test_no_rate_is_fast(self) -> None:
        limiter = RateLimiter()
        started = time.monotonic()
        for _ in range(5):
            await limiter.acquire()
        assert time.monotonic() - started < 1.0

    async def test_limited_rate_spaces_requests(self) -> None:
        # 10 req/s, burst 1: first token immediate, second waits ~0.1s.
        limiter = RateLimiter(rate_per_second=10, burst=1)
        started = time.monotonic()
        await limiter.acquire()
        await limiter.acquire()
        elapsed = time.monotonic() - started
        assert elapsed >= 0.08

    async def test_burst_allows_burst(self) -> None:
        limiter = RateLimiter(rate_per_second=1, burst=5)
        started = time.monotonic()
        for _ in range(3):
            await limiter.acquire()
        # Burst permits immediate consumption.
        assert time.monotonic() - started < 0.5


# ── Retry ───────────────────────────────────────────────────


class TestRetry:
    async def test_retries_transient_then_succeeds(self) -> None:
        calls = {"n": 0}

        async def flaky() -> str:
            calls["n"] += 1
            if calls["n"] < 3:
                raise BrowserTimeoutError("boom")
            return "ok"

        result = await retry_async(flaky, max_retries=3, backoff_base_ms=1)
        assert result == "ok"
        assert calls["n"] == 3

    async def test_raises_after_max_retries(self) -> None:
        async def always_fail() -> None:
            raise BrowserTimeoutError("boom")

        with pytest.raises(BrowserTimeoutError):
            await retry_async(always_fail, max_retries=2, backoff_base_ms=1)

    async def test_non_retryable_propagates_immediately(self) -> None:
        async def bad() -> None:
            raise ValueError("not retryable")

        with pytest.raises(ValueError):
            await retry_async(bad, max_retries=5, backoff_base_ms=1)

    async def test_custom_retryable_predicate(self) -> None:
        calls = {"n": 0}

        async def flaky() -> str:
            calls["n"] += 1
            if calls["n"] < 2:
                raise ValueError("transient")
            return "ok"

        result = await retry_async(
            flaky,
            max_retries=3,
            backoff_base_ms=1,
            retryable=lambda e: isinstance(e, ValueError),
        )
        assert result == "ok"


# ── Fingerprint ─────────────────────────────────────────────


class TestFingerprint:
    def test_generates_valid(self) -> None:
        fp = FingerprintRandomizer().generate()
        assert fp.user_agent
        assert fp.user_agent.startswith("Mozilla/5.0")
        assert fp.viewport[0] > 0 and fp.viewport[1] > 0
        assert fp.device_scale_factor >= 1
        assert fp.locale

    def test_respects_disable_randomization(self) -> None:
        cfg = FingerprintConfig(
            randomize_user_agent=False,
            randomize_locale=False,
            randomize_timezone=False,
            randomize_device_scale_factor=False,
            randomize_viewport=False,
        )
        base = FingerprintRandomizer(cfg).generate()
        second = FingerprintRandomizer(cfg).generate()
        assert base.user_agent == second.user_agent
        assert base.locale == second.locale
        assert base.viewport == second.viewport


# ── Captcha detection ───────────────────────────────────────


class TestCaptcha:
    async def test_detects_recaptcha(self) -> None:
        page = _FakePage(selectors={".g-recaptcha"})
        check = await CaptchaDetector().check(page, url="https://example.com/x")
        assert check.detected is True
        assert check.provider == "recaptcha"

    async def test_detects_cloudflare_by_url(self) -> None:
        page = _FakePage()
        check = await CaptchaDetector().check(page, url="https://example.com/cdn-cgi/challenge")
        assert check.detected is True
        assert check.provider == "cloudflare"

    async def test_clean_page_not_detected(self) -> None:
        page = _FakePage()
        check = await CaptchaDetector().check(page, url="https://example.com/products")
        assert check.detected is False

    async def test_disabled_detector(self) -> None:
        page = _FakePage(selectors={".g-recaptcha"})
        check = await CaptchaDetector(enabled=False).check(page)
        assert check.detected is False


# ── Request interception ────────────────────────────────────


class _FakeRoute:
    def __init__(self) -> None:
        self.aborted = None
        self.continued = False
        self.headers = None

    async def abort(self, reason: str) -> None:
        self.aborted = reason

    async def continue_(self, headers=None) -> None:
        self.continued = True
        self.headers = headers


class _FakeRequest:
    def __init__(self, resource_type="document", url="https://example.com/x", headers=None):
        self._rt = resource_type
        self._url = url
        self._headers = headers or {}

    def resource_type(self) -> str:
        return self._rt

    def url(self) -> str:
        return self._url

    def headers(self) -> dict:
        return self._headers


class TestInterceptor:
    async def test_blocks_resource_type(self) -> None:
        interceptor = RequestInterceptor(block_resource_types=["image"])
        route = _FakeRoute()
        await interceptor.handler(route, _FakeRequest(resource_type="image"))
        assert route.aborted == "blockedtype"
        assert route.continued is False

    async def test_blocks_domain(self) -> None:
        interceptor = RequestInterceptor()
        route = _FakeRoute()
        await interceptor.handler(route, _FakeRequest(url="https://cdn.doubleclick.net/x"))
        assert route.aborted == "blockedhost"

    async def test_injects_headers(self) -> None:
        interceptor = RequestInterceptor(inject_headers={"X-Foo": "bar"})
        route = _FakeRoute()
        await interceptor.handler(
            route,
            _FakeRequest(headers={"Accept": "text/html"}),
        )
        assert route.continued is True
        assert route.headers["X-Foo"] == "bar"
        assert route.headers["Accept"] == "text/html"


# ── Cookies ─────────────────────────────────────────────────


class TestCookieManager:
    def test_roundtrip(self, tmp_path) -> None:
        mgr = CookieManager(str(tmp_path / "cookies.json"))
        mgr.save("jar1", [{"name": "a", "value": "1", "domain": ".example.com"}])
        loaded = mgr.load("jar1")
        assert loaded[0]["name"] == "a"
        assert "jar1" in mgr.list_names()

    def test_missing_jar_returns_empty(self, tmp_path) -> None:
        mgr = CookieManager(str(tmp_path / "cookies.json"))
        assert mgr.load("nope") == []

    def test_delete(self, tmp_path) -> None:
        mgr = CookieManager(str(tmp_path / "cookies.json"))
        mgr.save("jar1", [{"name": "a"}])
        mgr.delete("jar1")
        assert "jar1" not in mgr.list_names()

    def test_clear_all(self, tmp_path) -> None:
        mgr = CookieManager(str(tmp_path / "cookies.json"))
        mgr.save("jar1", [{"name": "a"}])
        mgr.clear_all()
        assert mgr.list_names() == []


# ── Sessions ────────────────────────────────────────────────


class TestSessionManager:
    def test_save_load(self, tmp_path) -> None:
        mgr = SessionManager(str(tmp_path))
        mgr.save_state("walmart", {"cookies": [{"name": "a"}]})
        assert mgr.session_exists("walmart")
        assert mgr.load_state("walmart")["cookies"][0]["name"] == "a"
        assert "walmart" in mgr.list_sessions()

    def test_missing_returns_empty(self, tmp_path) -> None:
        mgr = SessionManager(str(tmp_path))
        assert mgr.load_state("nope") == {}

    def test_path_sanitized(self, tmp_path) -> None:
        mgr = SessionManager(str(tmp_path))
        mgr.save_state("../../evil", {"cookies": []})
        # Saved under a sanitized filename, not outside the dir.
        files = list(tmp_path.glob("*.json"))
        assert len(files) == 1
        assert ".." not in files[0].name

    def test_delete(self, tmp_path) -> None:
        mgr = SessionManager(str(tmp_path))
        mgr.save_state("s", {"cookies": []})
        mgr.delete("s")
        assert mgr.session_exists("s") is False


# ── Proxy manager ───────────────────────────────────────────


class TestProxyManager:
    def test_no_proxies_returns_none(self) -> None:
        assert ProxyManager().get_proxy() is None

    def test_round_robin(self) -> None:
        pm = ProxyManager(
            BrowserProxyConfig(
                proxies=[
                    ProxyConfig(url="http://p1:8080"),
                    ProxyConfig(url="http://p2:8080"),
                ]
            )
        )
        first = pm.get_proxy()
        second = pm.get_proxy()
        assert first["server"] == "http://p1:8080"
        assert second["server"] == "http://p2:8080"

    def test_bans_after_failures(self) -> None:
        pm = ProxyManager(
            BrowserProxyConfig(
                proxies=[ProxyConfig(url="http://p1:8080")],
                max_failures_before_ban=2,
            )
        )
        proxy = pm.get_proxy()
        pm.mark_failure(proxy)
        pm.mark_failure(proxy)
        with pytest.raises(ProxyExhaustedError):
            pm.get_proxy()

    def test_success_resets_ban(self) -> None:
        pm = ProxyManager(
            BrowserProxyConfig(
                proxies=[ProxyConfig(url="http://p1:8080")],
                max_failures_before_ban=2,
            )
        )
        proxy = pm.get_proxy()
        pm.mark_failure(proxy)
        pm.mark_success(proxy)
        pm.mark_failure(proxy)
        # Not banned because a success reset the counter (1 < 2).
        assert pm.get_proxy()["server"] == "http://p1:8080"

    def test_credentials_included(self) -> None:
        pm = ProxyManager(
            BrowserProxyConfig(
                proxies=[
                    ProxyConfig(url="http://proxy:8080", username="u", password="p")
                ]
            )
        )
        proxy = pm.get_proxy()
        assert proxy["username"] == "u"
        assert proxy["password"] == "p"


# ── BrowserManager context options ──────────────────────────


class TestBrowserManager:
    def test_context_options_apply_fingerprint_and_proxy(self) -> None:
        mgr = BrowserManager(BrowserConfig(fingerprint=FingerprintConfig(enabled=True)))
        opts = mgr._context_options(proxy={"server": "http://p:1"}, fingerprint=None)
        assert opts["viewport"]["width"] > 0
        assert opts["proxy"]["server"] == "http://p:1"
        assert opts["user_agent"].startswith("Mozilla/5.0")
        assert opts["locale"]

    def test_context_options_no_proxy_when_none_configured(self) -> None:
        mgr = BrowserManager(BrowserConfig())
        opts = mgr._context_options(proxy=None, fingerprint=None)
        assert "proxy" not in opts


# ── PagePool ────────────────────────────────────────────────


class TestPagePool:
    async def test_checkout_checkin_reuses(self) -> None:
        manager = _FakeBrowserManager()
        pool = PagePool(manager, max_size=2, max_idle_seconds=60, wait_timeout_seconds=1)
        p1 = await pool.checkout()
        await pool.checkin(p1)
        p2 = await pool.checkout()
        assert p1 is p2  # same page reused

    async def test_capacity_raises_timeout(self) -> None:
        manager = _FakeBrowserManager()
        pool = PagePool(manager, max_size=1, max_idle_seconds=60, wait_timeout_seconds=0.2)
        _held = await pool.checkout()
        with pytest.raises(BrowserPoolTimeoutError):
            await pool.checkout()

    async def test_discard_removes_from_in_use(self) -> None:
        manager = _FakeBrowserManager()
        pool = PagePool(manager, max_size=2, max_idle_seconds=60, wait_timeout_seconds=1)
        p1 = await pool.checkout()
        await pool.discard(p1)
        assert pool.in_use_count == 0

    async def test_clear_resets(self) -> None:
        manager = _FakeBrowserManager()
        pool = PagePool(manager, max_size=2, max_idle_seconds=60, wait_timeout_seconds=1)
        p1 = await pool.checkout()
        await pool.checkin(p1)
        await pool.clear()
        assert pool.size == 0


# ── Crawler (with fakes) ────────────────────────────────────


def _make_crawler(
    manager: _FakeBrowserManager | None = None,
    *,
    config: BrowserConfig | None = None,
) -> Crawler:
    manager = manager or _FakeBrowserManager()
    cfg = config or BrowserConfig(
        request_delay_min_ms=0,
        request_delay_max_ms=0,
        max_pages=2,
    )
    return Crawler(
        manager,
        rate_limiter=RateLimiter(),  # no artificial delays
        config=cfg,
    )


class TestCrawler:
    async def test_fetch_returns_result(self) -> None:
        crawler = _make_crawler()
        result = await crawler.fetch("https://example.com/p", use_pool=True)
        assert isinstance(result, CrawlResult)
        assert result.final_url == "https://example.com/p"
        assert result.status == 200
        assert result.title == "Test"
        assert result.html is not None

    async def test_fetch_uses_session_and_cookies(self, tmp_path) -> None:
        cfg = BrowserConfig(
            request_delay_min_ms=0,
            request_delay_max_ms=0,
            max_pages=2,
            session_dir=str(tmp_path / "sessions"),
            cookie_file=str(tmp_path / "cookies.json"),
        )
        crawler = _make_crawler(config=cfg)
        result = await crawler.fetch(
            "https://example.com/p",
            session="s1",
            cookies_name="jar1",
            use_pool=False,
        )
        assert result.final_url == "https://example.com/p"
        # Session + cookie state persisted to the temp dir.
        assert (tmp_path / "sessions" / "s1.json").exists()
        assert (tmp_path / "cookies.json").exists()

    async def test_fetch_detects_captcha_returns_blocked(self) -> None:
        manager = _FakeBrowserManager(page_factory=lambda: _FakePage(selectors={".g-recaptcha"}))
        crawler = _make_crawler(manager)
        result = await crawler.fetch("https://example.com/x", use_pool=False)
        assert result.blocked is True
        assert result.captcha is not None
        assert result.captcha.detected is True

    async def test_fetch_raise_on_captcha(self) -> None:
        from app.browser.errors import CaptchaDetectedError

        manager = _FakeBrowserManager(page_factory=lambda: _FakePage(selectors={".g-recaptcha"}))
        crawler = _make_crawler(manager)
        with pytest.raises(CaptchaDetectedError):
            await crawler.fetch("https://example.com/x", use_pool=False, raise_on_captcha=True)


# ── Error hierarchy ─────────────────────────────────────────


class TestErrors:
    def test_hierarchy(self) -> None:
        from app.browser.errors import BrowserAutomationError

        for exc in (BrowserPoolTimeoutError, BrowserTimeoutError, BrowserRateLimitError, ProxyError):
            assert issubclass(exc, BrowserAutomationError)
