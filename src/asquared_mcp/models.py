"""Pydantic input/output models for MCP tool calls."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator

ValidRecipient = Literal["claude-web", "claude-code", "codex", "alex", "broadcast"]
ValidKind = Literal[
    "status",
    "question",
    "answer",
    "handoff",
    "note",
    "stop_and_ask",
    "task_complete",
]
MAX_PAYLOAD_BYTES = 64 * 1024
ThreadId = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")]
ThreadTitle = Annotated[str, Field(min_length=1, max_length=200)]


class CoordPostInput(BaseModel):
    to_agent: ValidRecipient
    kind: ValidKind
    payload: dict[str, Any]
    thread_id: ThreadId | None = None

    @field_validator("payload")
    @classmethod
    def _payload_under_size_cap(cls, v: dict[str, Any]) -> dict[str, Any]:
        serialized = json.dumps(v, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(serialized) > MAX_PAYLOAD_BYTES:
            raise ValueError("payload serialized JSON must be <= 65536 bytes")
        return v


class CoordReadInput(BaseModel):
    since_id: int | None = Field(default=None, ge=0)
    thread_id: ThreadId | None = None
    kinds: list[ValidKind] | None = None
    unread_only: bool = False
    limit: int = Field(default=50, ge=1, le=200)


class CoordThreadsInput(BaseModel):
    action: Literal["create", "list", "close"]
    thread_id: ThreadId | None = None
    title: ThreadTitle | None = None
    include_closed: bool = False


class CoordAckInput(BaseModel):
    message_ids: list[int] = Field(..., min_length=1, max_length=200)


class CoordStatusInput(BaseModel):
    summary: str = Field(..., max_length=500)
    thread_id: ThreadId | None = None


class NotifyResult(BaseModel):
    notified: bool
    error: str | None = None
    reason: str | None = None
