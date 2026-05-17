# OAuth 2.0 Client Credentials Design

**Historical note:** path references inside this spec use the pre-rename form
`src/pfit_coord_mcp/`. The active code lives at `src/asquared_mcp/` after the
2026-05-17 rename.

**Packet:** PACKET-COORD-MCP-04  
**Date:** 2026-04-28  
**Status:** Approved for implementation

## Problem

Claude Web's connector uses the MCP OAuth discovery flow (RFC 9728 + RFC 8414 + RFC 7591).
The server only supports static Bearer tokens, so all connector auth attempts end in 401.
ChatGPT and Gemini connectors follow the same OAuth pattern.

## Goal

Allow hosted AI connectors (Claude Web, and future ChatGPT/Gemini) to authenticate via
OAuth 2.0 client credentials without breaking existing Claude Code and Codex Bearer token auth.

## Non-goals

- Authorization code flow (no user-consent redirect page needed)
- Dynamic client registration (admin controls all credentials)
- Refresh tokens (access tokens are reissued at expiry; connectors re-authenticate)
- JWT access tokens (opaque tokens stored in SQLite are sufficient)

## Design

### Config shape

New `[oauth]` block in `config.toml` and `config.toml.example`:

```toml
[oauth]
token_ttl_seconds = 86400  # 24-hour default

[oauth.clients]
"ccw_<id>" = { secret = "ccs_<secret>", agent_id = "claude-web" }
# "ccw_<id>" = { secret = "ccs_<secret>", agent_id = "chatgpt" }
```

- `client_id` prefix: `ccw_` (coord-client)
- `client_secret` prefix: `ccs_` (coord-client-secret)
- `agent_id`: any string; maps directly to `from_agent`/`to_agent` in messages
- `VALID_AGENT_IDS` validator in `config.py` applies only to `[tokens]`; OAuth clients
  are admin-configured so no enum check is applied

When adding a new connector: admin asks Claude Code to generate a `client_id`/`secret` pair,
adds one line to `config.toml`, restarts the server, and pastes credentials into the
connector UI. No code changes required.

### New file: `src/pfit_coord_mcp/oauth.py`

Handles all OAuth routes. Receives `Config` at construction.

**Base URL** — derived from the first HTTPS entry in `config.allowed_origins`
(e.g. `https://mcp.asquaredhome.com`). No new config field.

#### `GET /.well-known/oauth-protected-resource`

RFC 9728. No auth required.

```json
{
  "resource": "<base_url>",
  "authorization_servers": ["<base_url>"]
}
```

#### `GET /.well-known/oauth-authorization-server`

RFC 8414. No auth required.

```json
{
  "issuer": "<base_url>",
  "token_endpoint": "<base_url>/token",
  "grant_types_supported": ["client_credentials"],
  "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"]
}
```

No `authorization_endpoint` — authorization code flow is not supported.

#### `POST /token`

No auth required. Accepts `application/x-www-form-urlencoded`.

Validation:

1. `grant_type` must be `client_credentials`
2. `client_id` must exist in `config.oauth.clients`
3. `client_secret` must match via `secrets.compare_digest`

On success: generates `oat_`-prefixed token (`secrets.token_urlsafe(32)`), stores in
`oauth_access_tokens` table with `expires_at = now + token_ttl_seconds`, returns:

```json
{"access_token": "oat_...", "token_type": "Bearer", "expires_in": 86400}
```

Error responses follow RFC 6749 §5.2:

- Wrong grant type → `{"error": "unsupported_grant_type"}`
- Bad credentials → `{"error": "invalid_client"}` (same response for unknown id and wrong secret)

#### `POST /register`

No auth required. Returns 400:

```json
{
  "error": "registration_not_supported",
  "message": "Dynamic registration is disabled. Request credentials from the administrator."
}
```

### Auth layer (`src/pfit_coord_mcp/auth.py`)

**Public OAuth paths** (bypass both `BearerTokenMiddleware` and `OriginAllowlistMiddleware`):

```python
OAUTH_PUBLIC_PATHS = frozenset({
    "/.well-known/oauth-protected-resource",
    "/.well-known/oauth-authorization-server",
    "/token",
    "/register",
})
```

**`BearerTokenMiddleware._resolve_agent_id`** extends to two lookups:

1. Check `token_map` (static config tokens) — unchanged
2. If not found, call `lookup_oauth_token(db_path, token)` — returns `agent_id` or `None`

The middleware receives `db_path` as a new constructor argument (alongside `token_map`).

### SQLite schema (`src/pfit_coord_mcp/store.py`)

New table appended to `SCHEMA`:

```sql
CREATE TABLE IF NOT EXISTS oauth_access_tokens (
    token      TEXT PRIMARY KEY,
    client_id  TEXT NOT NULL,
    agent_id   TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
```

Two new functions:

```python
def store_oauth_token(db_path, token, client_id, agent_id, expires_at) -> None
def lookup_oauth_token(db_path, token) -> sqlite3.Row | None  # None if missing or expired; both cases indistinguishable to caller
```

Expired token cleanup is lazy (checked at lookup, not purged on schedule). Acceptable at
personal scale.

### Route registration (`src/pfit_coord_mcp/server.py`)

OAuth routes added before `Mount("/", app=mcp_asgi)` so they resolve first:

```python
routes=[
    Route(HEALTH_PATH, health),
    Route("/.well-known/oauth-protected-resource", oauth_resource),
    Route("/.well-known/oauth-authorization-server", oauth_server_meta),
    Route("/token", oauth_token, methods=["POST"]),
    Route("/register", oauth_register, methods=["POST"]),
    Mount("/", app=mcp_asgi),
]
```

### Config model (`src/pfit_coord_mcp/config.py`)

New models:

```python
class OAuthClientConfig(BaseModel):
    secret: str
    agent_id: str

class OAuthConfig(BaseModel):
    token_ttl_seconds: int = 86400
    clients: dict[str, OAuthClientConfig] = Field(default_factory=dict)
```

`Config` gains `oauth: OAuthConfig = Field(default_factory=OAuthConfig)`.
`load_config` reads `raw.get("oauth", {})`.

## Testing (`tests/test_oauth.py`)

| Test | Expected |
| ---- | -------- |
| GET `/.well-known/oauth-protected-resource` | 200, correct shape |
| GET `/.well-known/oauth-authorization-server` | 200, correct shape, no `authorization_endpoint` |
| POST `/token` valid credentials | 200, `access_token` present |
| POST `/token` wrong secret | 400, `invalid_client` |
| POST `/token` unknown client_id | 400, `invalid_client` |
| POST `/token` wrong grant type | 400, `unsupported_grant_type` |
| OAuth access token used as Bearer on `/mcp` | auth passes (200 or MCP-layer response) |
| Expired access token on `/mcp` | 401 |
| POST `/register` | 400, `registration_not_supported` |
| Static Bearer token still works (regression) | agent resolves correctly |

## Files changed

| File | Change |
| ---- | ------ |
| `src/pfit_coord_mcp/oauth.py` | New — OAuth route handlers |
| `src/pfit_coord_mcp/config.py` | Add `OAuthClientConfig`, `OAuthConfig`, extend `Config` |
| `src/pfit_coord_mcp/store.py` | Add `oauth_access_tokens` table + 2 functions |
| `src/pfit_coord_mcp/auth.py` | Add bypass list, extend token lookup to SQLite |
| `src/pfit_coord_mcp/server.py` | Register OAuth routes, pass `db_path` to middleware |
| `config.toml.example` | Add commented `[oauth]` block |
| `config.toml` (codeserver) | Add `[oauth]` with claude-web client credentials |
| `tests/test_oauth.py` | New — OAuth test suite |
