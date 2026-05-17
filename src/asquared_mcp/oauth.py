"""OAuth 2.0 authorization code + PKCE and client credentials routes."""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from .config import Config
from .store import consume_auth_code, store_auth_code, store_oauth_token

_LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "::1"}
_AUTH_CODE_TTL_SECONDS = 600


def _base_url(allowed_origins: list[str]) -> str:
    """Return the first HTTPS non-local origin as the OAuth issuer base URL."""
    for origin in allowed_origins:
        if not origin.startswith("https://"):
            continue
        host = origin.removeprefix("https://").split(":")[0]
        if host not in _LOCAL_HOSTNAMES:
            return origin
    return allowed_origins[0] if allowed_origins else "http://localhost:8765"


def _pkce_verify(code_verifier: str, code_challenge: str) -> bool:
    """Return True if SHA256(code_verifier) == code_challenge (base64url, no padding)."""
    digest = hashlib.sha256(code_verifier.encode()).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return secrets.compare_digest(computed, code_challenge)


def build_oauth_routes(config: Config) -> list[Route]:
    """Return Starlette Route objects for all OAuth endpoints."""
    base = _base_url(config.allowed_origins)

    async def oauth_protected_resource(_request: Request) -> Response:
        return JSONResponse({
            "resource": base,
            "authorization_servers": [base],
        })

    async def oauth_authorization_server(_request: Request) -> Response:
        return JSONResponse({
            "issuer": base,
            "authorization_endpoint": f"{base}/authorize",
            "token_endpoint": f"{base}/token",
            "grant_types_supported": ["authorization_code", "client_credentials"],
            "response_types_supported": ["code"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": [
                "client_secret_post",
                "client_secret_basic",
            ],
        })

    async def oauth_authorize(request: Request) -> Response:
        params = request.query_params
        response_type = params.get("response_type", "")
        client_id = params.get("client_id", "")
        redirect_uri = params.get("redirect_uri", "")
        code_challenge = params.get("code_challenge", "")
        code_challenge_method = params.get("code_challenge_method", "")
        state = params.get("state", "")

        if response_type != "code":
            return JSONResponse({"error": "unsupported_response_type"}, status_code=400)
        if not code_challenge or code_challenge_method != "S256":
            return JSONResponse(
                {"error": "invalid_request", "error_description": "PKCE S256 required"},
                status_code=400,
            )
        if not redirect_uri:
            return JSONResponse(
                {"error": "invalid_request", "error_description": "redirect_uri required"},
                status_code=400,
            )
        client = config.oauth.clients.get(client_id)
        if client is None:
            return JSONResponse({"error": "unauthorized_client"}, status_code=400)

        code = "ac_" + secrets.token_urlsafe(32)
        expires_at = (
            datetime.now(UTC) + timedelta(seconds=_AUTH_CODE_TTL_SECONDS)
        ).isoformat(timespec="seconds")
        store_auth_code(
            config.server.db_path,
            code=code,
            client_id=client_id,
            agent_id=client.agent_id,
            code_challenge=code_challenge,
            redirect_uri=redirect_uri,
            expires_at=expires_at,
        )
        qs = urlencode({"code": code, "state": state} if state else {"code": code})
        return RedirectResponse(f"{redirect_uri}?{qs}", status_code=302)

    async def oauth_token(request: Request) -> Response:
        form = await request.form()
        grant_type = str(form.get("grant_type") or "")

        if grant_type == "authorization_code":
            code = str(form.get("code") or "")
            redirect_uri = str(form.get("redirect_uri") or "")
            client_id = str(form.get("client_id") or "")
            code_verifier = str(form.get("code_verifier") or "")

            row = consume_auth_code(config.server.db_path, code)
            if row is None:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            if row["client_id"] != client_id:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            if row["redirect_uri"] != redirect_uri:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            if not _pkce_verify(code_verifier, row["code_challenge"]):
                return JSONResponse({"error": "invalid_grant"}, status_code=400)

            token = "oat_" + secrets.token_urlsafe(32)
            expires_at = (
                datetime.now(UTC) + timedelta(seconds=config.oauth.token_ttl_seconds)
            ).isoformat(timespec="seconds")
            store_oauth_token(
                config.server.db_path, token, client_id, str(row["agent_id"]), expires_at
            )
            return JSONResponse({
                "access_token": token,
                "token_type": "Bearer",
                "expires_in": config.oauth.token_ttl_seconds,
            })

        if grant_type == "client_credentials":
            client_id = str(form.get("client_id") or "")
            client_secret = str(form.get("client_secret") or "")

            client = config.oauth.clients.get(client_id)
            expected = client.secret if client is not None else secrets.token_urlsafe(32)
            match = secrets.compare_digest(client_secret, expected)
            if client is None or not match:
                return JSONResponse({"error": "invalid_client"}, status_code=400)

            token = "oat_" + secrets.token_urlsafe(32)
            expires_at = (
                datetime.now(UTC) + timedelta(seconds=config.oauth.token_ttl_seconds)
            ).isoformat(timespec="seconds")
            store_oauth_token(
                config.server.db_path, token, client_id, client.agent_id, expires_at
            )
            return JSONResponse({
                "access_token": token,
                "token_type": "Bearer",
                "expires_in": config.oauth.token_ttl_seconds,
            })

        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

    async def oauth_register(_request: Request) -> Response:
        return JSONResponse(
            {
                "error": "registration_not_supported",
                "message": (
                    "Dynamic registration is disabled. "
                    "Request credentials from the administrator."
                ),
            },
            status_code=400,
        )

    return [
        Route("/.well-known/oauth-protected-resource", oauth_protected_resource),
        Route("/.well-known/oauth-authorization-server", oauth_authorization_server),
        Route("/authorize", oauth_authorize),
        Route("/token", oauth_token, methods=["POST"]),
        Route("/register", oauth_register, methods=["POST"]),
    ]
