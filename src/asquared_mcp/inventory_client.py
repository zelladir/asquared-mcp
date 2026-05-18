"""Async HTTP client for the home-inventory API.

One ``InventoryClient`` instance per running MCP server. The httpx
``AsyncClient`` is created lazily on first use and shared across tool
calls; on server shutdown the lifespan hook in ``server.py`` calls
``aclose()``.

Auth posture: the client passes ``Authorization: Bearer <token>`` on
every request. The token comes from ``[home_inventory]`` in the server
config and is a scoped MCP token minted via the home-inventory API's
``POST /auth/mcp-tokens`` endpoint (see home-inventory PR #25 / prompt
21 for the mint surface).

Endpoint routing: the home-inventory production API is behind
oauth2-proxy at ``inventory.asquaredhome.com``. Server-to-server bearer
calls go through a sibling location (``/mcp-api/*``) that bypasses
oauth2-proxy and lets the api's ``security.py`` validate the bearer
against its ``mcp_tokens`` table.
"""

from __future__ import annotations

import re
from typing import Any

import httpx


DEFAULT_TIMEOUT_SECONDS = 20.0
REFERENCE_ID_RE = re.compile(r"^HI-[A-Z0-9]{6,16}$")


class InventoryClientError(RuntimeError):
    """Raised when the home-inventory API returns a non-2xx response."""


class InventoryClient:
    """Async HTTP client over the home-inventory API.

    Tests inject a custom transport via the constructor's ``transport``
    arg so they can stub responses without a live server.
    """

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if not token:
            raise ValueError("token is required")
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout_seconds = timeout_seconds
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            kwargs: dict[str, Any] = {
                "base_url": self._base_url,
                "headers": {
                    "Authorization": f"Bearer {self._token}",
                    "Accept": "application/json",
                },
                "timeout": self._timeout_seconds,
            }
            if self._transport is not None:
                kwargs["transport"] = self._transport
            self._client = httpx.AsyncClient(**kwargs)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> Any:
        client = await self._ensure_client()
        response = await client.get(path, params=params)
        if response.status_code == 404:
            raise LookupError(f"not_found:{path}")
        if response.status_code >= 400:
            raise InventoryClientError(
                f"{response.status_code} from {path}: {response.text[:200]}"
            )
        return response.json()

    async def search_items(
        self, *, query: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        return await self._get("/items", params={"q": query, "limit": int(limit)})

    async def get_item(self, *, item_id_or_ref: str) -> dict[str, Any]:
        try:
            return await self._get(f"/items/{item_id_or_ref}")
        except LookupError:
            # Fall back to search when the input looks like an HI-XXXX
            # reference id; the items endpoint only matches on UUID.
            if REFERENCE_ID_RE.match(item_id_or_ref):
                hits = await self.search_items(query=item_id_or_ref, limit=1)
                if isinstance(hits, list) and hits:
                    return hits[0]
            raise

    async def list_locations(
        self, *, query: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": int(limit)}
        if query:
            params["q"] = query
        return await self._get("/locations", params=params)

    async def list_location_items(
        self, *, location_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        return await self._get(
            f"/locations/{location_id}/items", params={"limit": int(limit)}
        )

    async def get_location_map(self, *, floor_id: str) -> dict[str, Any]:
        return await self._get(f"/locations/{floor_id}/map")
