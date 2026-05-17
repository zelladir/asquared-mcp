"""Starlette middleware: Bearer-token auth + Origin allowlist."""

from __future__ import annotations

import secrets
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from .store import lookup_oauth_token

AGENT_ID_STATE_KEY = "agent_id"
HEALTH_PATH = "/health"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
UNAUTHORIZED_RESPONSE = {"error": "unauthorized", "message": "Unauthorized"}

OAUTH_PUBLIC_PATHS = frozenset({
    "/.well-known/oauth-protected-resource",
    "/.well-known/oauth-authorization-server",
    "/authorize",
    "/token",
    "/register",
})

_BYPASS_PATHS = frozenset({HEALTH_PATH}) | OAUTH_PUBLIC_PATHS


class BearerTokenMiddleware(BaseHTTPMiddleware):
    """Validate `Authorization: Bearer <token>`; attach agent_id to request.state.

    /health and OAuth public paths are unauthenticated (bypass).
    Token resolution checks static config tokens first, then SQLite OAuth tokens.
    """

    def __init__(self, app: ASGIApp, token_map: dict[str, str], db_path: str = "") -> None:
        super().__init__(app)
        self.token_map = token_map
        self.db_path = db_path

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in _BYPASS_PATHS:
            return await call_next(request)

        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token or token.strip() != token or " " in token:
            return JSONResponse(UNAUTHORIZED_RESPONSE, status_code=401)
        agent_id = self._resolve_agent_id(token)
        if agent_id is None:
            return JSONResponse(UNAUTHORIZED_RESPONSE, status_code=401)
        setattr(request.state, AGENT_ID_STATE_KEY, agent_id)
        request.scope[AGENT_ID_STATE_KEY] = agent_id
        return await call_next(request)

    def _resolve_agent_id(self, presented_token: str) -> str | None:
        # 1. Static config tokens (constant-time comparison)
        matched_agent: str | None = None
        for configured_token, agent_id in self.token_map.items():
            if secrets.compare_digest(presented_token, configured_token):
                matched_agent = agent_id
        if matched_agent is not None:
            return matched_agent
        # 2. OAuth access tokens from SQLite
        if self.db_path:
            row = lookup_oauth_token(self.db_path, presented_token)
            if row is not None:
                return str(row["agent_id"])
        return None


class OriginAllowlistMiddleware(BaseHTTPMiddleware):
    """DNS-rebinding defense per MCP streamable HTTP spec.

    Rules:
    - /health and OAuth public paths are exempt.
    - Requests with no Origin header pass through (CLI / curl / non-browser).
    - Requests with an Origin header must match one of `allowed_origins`.
    - Requests that arrive for a configured public HTTPS host pass through even
      when the client Origin is a rotating hosted-client origin.
    """

    def __init__(self, app: ASGIApp, allowed_origins: list[str]) -> None:
        super().__init__(app)
        self.allowed_origins = set(allowed_origins)
        self.trusted_public_hosts = {
            parsed.hostname
            for origin in allowed_origins
            if (parsed := urlsplit(origin)).scheme == "https"
            and parsed.hostname is not None
            and parsed.hostname not in LOCAL_HOSTS
        }

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in _BYPASS_PATHS:
            return await call_next(request)
        origin = request.headers.get("origin")
        if origin is not None and origin not in self.allowed_origins:
            if request.url.hostname not in self.trusted_public_hosts:
                return JSONResponse(
                    {"error": "forbidden_origin", "message": "Origin not allowed"},
                    status_code=403,
                )
        return await call_next(request)
