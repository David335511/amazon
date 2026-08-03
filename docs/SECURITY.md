# Security (Phase 0)

Phase 0 introduces the first layer of API authentication and hardens CORS. It is
designed as the seam on which a full auth system (users, roles, JWT/OAuth) can be
built later without changing route code.

## What's implemented

### 1. API-key authentication
The entire `/api/v1/*` tree now requires a valid `X-API-Key` header **when
security is enabled**. Keys are checked with constant-time comparison
(`secrets.compare_digest`) to avoid timing side-channels.

| Scenario | Response |
|---|---|
| Missing key | `401 Unauthorized` |
| Invalid key | `403 Forbidden` |
| Valid key | request proceeds |
| Public path | always allowed (no key needed) |

**Public by default:** `/api/v1/health/live` and `/api/v1/health/ready` are
exempt so Render health checks and the keep-alive pinger keep working without a
key. Configure with `security.public_paths`.

### 2. CORS hardening
Fixed the `allow_origins=["*"]` + `allow_credentials=True` misconfiguration
(browsers reject that combination, and it weakened the policy). When the origin
set is wildcard, credentials are now forced off.

### 3. Config
```yaml
# config/development.yaml
security:
  enabled: false            # local dev: everything open
  api_keys: []              # accepted keys
  header_name: X-API-Key
  public_paths:
    - /api/v1/health
```

Environment overrides (for Render / production):
```
SECURITY_ENABLED=true
API_KEYS=key1,key2,key3
```
Generate a strong key:
```
.venv\Scripts\python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## How it's wired
- `app/core/security.py` — `SecurityConfig`, `authenticate()`, and the
  `require_api_key` FastAPI dependency.
- The dependency is attached once at the **router level**
  (`app/api/v1/__init__.py`), so every v1 route is protected without touching
  individual route files. When `enabled` is false it's a no-op, so local dev
  and the existing test suite are unaffected.
- `SecurityConfig` is a plain Pydantic model; `Settings.load()` applies the
  YAML block and then explicit `API_KEYS` / `SECURITY_ENABLED` env overrides.

## Extending later
The `require_api_key` dependency is the single auth seam. To move to JWT/OAuth:
swap the dependency's implementation (or add a second dependency) — routes and
the config plumbing stay unchanged. For fine-grained authorization, add
role/permission metadata to the API keys and check it inside the dependency.

## What's NOT covered yet (future phases)
- User accounts, roles, and per-user authorization.
- Rate limiting (flagged in reviews; `features.rate_limiting` is a stub).
- Secret rotation / per-client keys.
- The web dashboard (served at `/` and `/dashboard`) is not behind the API-key
  gate — it is read-only UI. Gate it separately if it ever writes data.

## Tests
`tests/test_security.py` — 12 tests: config parsing, public-path matching,
disabled/denied/allowed auth decisions, and full HTTP 401/403/200 + public-health
integration. Full suite: **386 passing**.
