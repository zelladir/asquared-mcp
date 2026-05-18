"""Pydantic input models for the home-inventory MCP tools.

Kept separate from ``models.py`` (which carries the coord_* shapes) so
the inventory expansion is a clean add: one module to disable, one to
re-enable.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class InventorySearchItemsInput(BaseModel):
    query: str = Field(min_length=1, description="Free-form search text.")
    limit: int = Field(default=20, ge=1, le=200)


class InventoryGetItemInput(BaseModel):
    item_id_or_ref: str = Field(
        min_length=1,
        description="Either a UUID or a reference id like HI-1234ABCD.",
    )


class InventoryListLocationsInput(BaseModel):
    query: str | None = Field(
        default=None,
        description="Optional name / kind / notes filter.",
    )
    limit: int = Field(default=50, ge=1, le=500)


class InventoryListLocationItemsInput(BaseModel):
    location_id: str = Field(min_length=1, description="UUID of the Location.")
    limit: int = Field(default=50, ge=1, le=500)


class InventoryGetLocationMapInput(BaseModel):
    floor_id: str = Field(
        min_length=1, description="UUID of a floor-kind Location."
    )
