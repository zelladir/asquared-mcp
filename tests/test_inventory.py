"""Tests for the home-inventory expansion: client + tools + wiring.

Server-layer tests use httpx ``MockTransport`` to stub the home-inventory
API; no live network is required.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from asquared_mcp.config import (
    Config,
    HomeInventoryConfig,
    PushoverConfig,
    ServerConfig,
)
from asquared_mcp.inventory_client import (
    InventoryClient,
    InventoryClientError,
)
from asquared_mcp.inventory_tools import register_inventory_tools
from asquared_mcp.server import (
    SERVER_INSTRUCTIONS,
    SERVER_README,
    _build_inventory_client,
    _server_readme_text,
    build_mcp,
)


# ---------------------------------------------------------------------------
# Client tests
# ---------------------------------------------------------------------------


def _routes_transport(routes: dict[str, Any]) -> httpx.MockTransport:
    """MockTransport keyed by request path prefix.

    A value can be a JSON-serializable response OR a callable
    (request) -> httpx.Response for custom logic.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        for prefix, payload in routes.items():
            if request.url.path.startswith(prefix):
                if callable(payload):
                    return payload(request)
                return httpx.Response(200, json=payload)
        return httpx.Response(404, json={"detail": "not_found"})

    return httpx.MockTransport(handler)


def _client(transport: httpx.MockTransport) -> InventoryClient:
    return InventoryClient(
        base_url="http://test.invalid",
        token="dev-token",
        transport=transport,
    )


def test_client_requires_base_url():
    with pytest.raises(ValueError):
        InventoryClient(base_url="", token="t")


def test_client_requires_token():
    with pytest.raises(ValueError):
        InventoryClient(base_url="x", token="")


@pytest.mark.asyncio
async def test_search_items_passes_query_and_authorization():
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        assert request.headers["authorization"] == "Bearer dev-token"
        assert request.url.params["q"] == "drill"
        assert request.url.params["limit"] == "5"
        return httpx.Response(200, json=[{"id": "1", "name": "drill"}])

    c = _client(httpx.MockTransport(handler))
    try:
        result = await c.search_items(query="drill", limit=5)
    finally:
        await c.aclose()
    assert result == [{"id": "1", "name": "drill"}]
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_get_item_by_uuid():
    transport = _routes_transport({"/items/abc": {"id": "abc", "name": "thing"}})
    c = _client(transport)
    try:
        result = await c.get_item(item_id_or_ref="abc")
    finally:
        await c.aclose()
    assert result["id"] == "abc"


@pytest.mark.asyncio
async def test_get_item_falls_back_to_search_on_ref_404():
    # First call (/items/HI-...) returns 404, then (/items?q=...) returns a hit.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/items/HI-"):
            return httpx.Response(404, json={"detail": "not found"})
        if request.url.path == "/items":
            assert request.url.params["q"] == "HI-1234ABCD"
            return httpx.Response(
                200,
                json=[{"id": "u", "reference_id": "HI-1234ABCD", "name": "drill"}],
            )
        return httpx.Response(500, json={})

    c = _client(httpx.MockTransport(handler))
    try:
        result = await c.get_item(item_id_or_ref="HI-1234ABCD")
    finally:
        await c.aclose()
    assert result["reference_id"] == "HI-1234ABCD"


@pytest.mark.asyncio
async def test_get_item_404_for_unknown_uuid_raises():
    transport = httpx.MockTransport(
        lambda r: httpx.Response(404, json={"detail": "not found"})
    )
    c = _client(transport)
    try:
        with pytest.raises(LookupError):
            await c.get_item(item_id_or_ref="nonexistent-uuid")
    finally:
        await c.aclose()


@pytest.mark.asyncio
async def test_list_locations_without_query():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/locations"
        assert "q" not in request.url.params
        return httpx.Response(200, json=[])

    c = _client(httpx.MockTransport(handler))
    try:
        result = await c.list_locations()
    finally:
        await c.aclose()
    assert result == []


@pytest.mark.asyncio
async def test_server_500_raises_inventory_client_error():
    transport = httpx.MockTransport(
        lambda r: httpx.Response(500, json={"detail": "boom"})
    )
    c = _client(transport)
    try:
        with pytest.raises(InventoryClientError):
            await c.search_items(query="x")
    finally:
        await c.aclose()


# ---------------------------------------------------------------------------
# Tool-registration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_mcp_without_inventory_skips_family():
    config = Config(
        server=ServerConfig(),
        tokens={},
        pushover=PushoverConfig(),
        allowed_origins=[],
        home_inventory=HomeInventoryConfig(),
    )
    mcp = build_mcp(config, inventory_client=None)
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert "coord_post" in names
    assert not any(n.startswith("inventory_") for n in names)


@pytest.mark.asyncio
async def test_build_mcp_with_inventory_registers_five_tools():
    config = Config(server=ServerConfig(), tokens={}, pushover=PushoverConfig())
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=[]))
    client = _client(transport)
    try:
        mcp = build_mcp(config, inventory_client=client)
        tools = await mcp.list_tools()
        names = {t.name for t in tools}
        assert {
            "inventory_search_items",
            "inventory_get_item",
            "inventory_list_locations",
            "inventory_list_location_items",
            "inventory_get_location_map",
        }.issubset(names)
    finally:
        await client.aclose()


def test_build_inventory_client_returns_none_when_unconfigured():
    config = Config()
    assert _build_inventory_client(config) is None


def test_build_inventory_client_constructs_when_configured():
    config = Config(
        home_inventory=HomeInventoryConfig(
            base_url="http://test.invalid",
            token="t",
        )
    )
    client = _build_inventory_client(config)
    assert client is not None


# ---------------------------------------------------------------------------
# Instructions + README resource
# ---------------------------------------------------------------------------


def test_instructions_constant_mentions_both_tool_families():
    assert "coord_" in SERVER_INSTRUCTIONS
    assert "inventory_" in SERVER_INSTRUCTIONS
    assert "docs://asquared-mcp/readme" in SERVER_INSTRUCTIONS


def test_readme_constant_lists_all_tools():
    for tool_name in (
        "coord_post",
        "coord_read",
        "coord_threads",
        "coord_ack",
        "coord_status",
        "inventory_search_items",
        "inventory_get_item",
        "inventory_list_locations",
        "inventory_list_location_items",
        "inventory_get_location_map",
    ):
        assert tool_name in SERVER_README, f"README missing {tool_name}"


def test_readme_resource_helper_returns_constant():
    # Just confirm the helper returns the canonical text. The MCP resource
    # registration itself is exercised in test_build_mcp_lists_readme_resource.
    assert _server_readme_text() == SERVER_README


@pytest.mark.asyncio
async def test_build_mcp_lists_readme_resource():
    config = Config()
    mcp = build_mcp(config, inventory_client=None)
    resources = await mcp.list_resources()
    uris = {str(r.uri) for r in resources}
    assert "docs://asquared-mcp/readme" in uris


@pytest.mark.asyncio
async def test_build_mcp_passes_instructions_to_fastmcp():
    config = Config()
    mcp = build_mcp(config, inventory_client=None)
    # FastMCP exposes the instructions on the underlying server attribute.
    # The exact accessor is SDK-version-dependent; try the public surfaces.
    instr = (
        getattr(mcp, "instructions", None)
        or getattr(getattr(mcp, "_mcp_server", None), "instructions", None)
        or getattr(mcp, "_instructions", None)
    )
    assert instr == SERVER_INSTRUCTIONS, (
        "FastMCP instructions field not set as expected; "
        "check the SDK version's accessor for InitializeResult.instructions"
    )
