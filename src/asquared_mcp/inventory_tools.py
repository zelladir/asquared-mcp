"""Register home-inventory tools on a FastMCP instance.

Called from ``server.build_mcp`` when ``[home_inventory]`` is configured.
Five read-only tools share one :class:`InventoryClient` (kept on the
caller's closure so the underlying httpx client is reused across all
tool invocations and torn down in the server's lifespan).

Tool naming convention: ``inventory_*`` prefix so the LLM (and human
readers) can distinguish these from the existing ``coord_*`` tools. Don't
rename without coordinating with downstream client configs.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from .inventory_client import InventoryClient, InventoryClientError
from .inventory_models import (
    InventoryGetItemInput,
    InventoryGetLocationMapInput,
    InventoryListLocationItemsInput,
    InventoryListLocationsInput,
    InventorySearchItemsInput,
)


def _error_payload(exc: Exception) -> dict[str, Any]:
    """Shape exceptions as a return value so the tool surfaces a
    readable error to the LLM without raising MCP protocol-level
    failure. Mirrors the convention in the coord_* tools.
    """

    return {
        "error": type(exc).__name__,
        "message": str(exc),
    }


def register_inventory_tools(mcp: FastMCP, client: InventoryClient) -> None:
    """Register the five home-inventory tools on ``mcp``.

    ``client`` is captured by closure; callers own its lifecycle (call
    ``client.aclose()`` on server shutdown).
    """

    @mcp.tool(
        name="inventory_search_items",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def inventory_search_items(
        params: InventorySearchItemsInput,
        ctx: Context,  # type: ignore[type-arg]
    ) -> dict[str, Any]:
        """Full-text search across the home-inventory item catalog.

        Matches against item name, manufacturer, model, serial, description,
        and reference id (HI-XXXXXXXX). Returns up to ``limit`` hits, most
        relevant first. Use when you need to find an item by any
        human-recognizable attribute (e.g. "Rigol oscilloscope", "USB-C
        hub", "HI-1234ABCD").

        Returns: ``{ items: [...], count: int }`` or
        ``{ error: ..., message: ... }`` on failure.
        """
        try:
            rows = await client.search_items(
                query=params.query, limit=params.limit
            )
        except (LookupError, InventoryClientError) as exc:
            return _error_payload(exc)
        return {"items": rows, "count": len(rows)}

    @mcp.tool(
        name="inventory_get_item",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def inventory_get_item(
        params: InventoryGetItemInput,
        ctx: Context,  # type: ignore[type-arg]
    ) -> dict[str, Any]:
        """Fetch one item by its UUID or HI-XXXXXXXX reference id.

        Returns the full item record: name, category, manufacturer, model,
        serial, quantity, condition, retail/actual/resale prices, status,
        location summary, tags, and metadata. Falls back to a search when
        the input is a reference id and the UUID lookup misses.

        Returns: ``{ item: {...} }`` or ``{ error: ..., message: ... }``.
        """
        try:
            row = await client.get_item(item_id_or_ref=params.item_id_or_ref)
        except (LookupError, InventoryClientError) as exc:
            return _error_payload(exc)
        return {"item": row}

    @mcp.tool(
        name="inventory_list_locations",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def inventory_list_locations(
        params: InventoryListLocationsInput,
        ctx: Context,  # type: ignore[type-arg]
    ) -> dict[str, Any]:
        """List Locations (rooms, shelves, bins, racks, floors).

        Optional ``query`` filters by name / kind / notes substring. Use
        this before ``inventory_list_location_items`` to find a Location
        UUID, or before ``inventory_get_location_map`` to find a floor.

        Returns: ``{ locations: [...], count: int }``.
        """
        try:
            rows = await client.list_locations(
                query=params.query, limit=params.limit
            )
        except (LookupError, InventoryClientError) as exc:
            return _error_payload(exc)
        return {"locations": rows, "count": len(rows)}

    @mcp.tool(
        name="inventory_list_location_items",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def inventory_list_location_items(
        params: InventoryListLocationItemsInput,
        ctx: Context,  # type: ignore[type-arg]
    ) -> dict[str, Any]:
        """List every Item physically assigned to a given Location.

        Use after ``inventory_list_locations`` resolves the Location UUID.
        Answers "what's in the workshop?" / "what's in rack 1?" style
        questions.

        Returns: ``{ items: [...], count: int }``.
        """
        try:
            rows = await client.list_location_items(
                location_id=params.location_id, limit=params.limit
            )
        except (LookupError, InventoryClientError) as exc:
            return _error_payload(exc)
        return {"items": rows, "count": len(rows)}

    @mcp.tool(
        name="inventory_get_location_map",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def inventory_get_location_map(
        params: InventoryGetLocationMapInput,
        ctx: Context,  # type: ignore[type-arg]
    ) -> dict[str, Any]:
        """Get the floor-plan map for a floor-kind Location.

        Returns the SVG background URL plus every child room's marker
        coordinates and item count. Errors with 422 ``not_a_floor`` if
        the location is not of kind='floor'.

        Returns: ``{ map: {...} }`` or ``{ error: ..., message: ... }``.
        """
        try:
            payload = await client.get_location_map(floor_id=params.floor_id)
        except (LookupError, InventoryClientError) as exc:
            return _error_payload(exc)
        return {"map": payload}
