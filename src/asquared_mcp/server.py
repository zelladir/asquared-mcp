"""FastMCP server with bearer-auth + origin-validated streamable HTTP transport."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextvars import ContextVar
from typing import Any

import uvicorn
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from . import __version__
from .auth import (
    AGENT_ID_STATE_KEY,
    HEALTH_PATH,
    BearerTokenMiddleware,
    OriginAllowlistMiddleware,
)
from .config import Config, load_config
from .oauth import build_oauth_routes
from .models import (
    CoordAckInput,
    CoordPostInput,
    CoordReadInput,
    CoordStatusInput,
    CoordThreadsInput,
)
from .notify import maybe_notify
from .store import (
    ack_messages,
    close_thread,
    create_thread,
    init_db,
    list_threads,
    post_message,
    read_messages,
)

logger = logging.getLogger(__name__)

# Per-request agent_id propagated from auth middleware. FastMCP tool handlers
# can't directly access starlette request.state, so the resolved agent_id is
# stashed in a contextvar inside a pure-ASGI middleware that runs after
# BearerTokenMiddleware. Tool handlers read it via _require_agent_id().
_current_agent: ContextVar[str | None] = ContextVar("_current_agent", default=None)


class AgentContextMiddleware:
    """Pure-ASGI middleware: copies scope['agent_id'] (set by BearerTokenMiddleware)
    into the _current_agent contextvar so tool handlers can read it.

    Why a top-level scope key instead of scope['state']: Starlette's
    request.state is a State() object (not a dict), and scope['state'] holds
    that object — it doesn't support .get('agent_id'). Writing a plain str at
    scope['agent_id'] keeps this pure-ASGI bridge simple.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        agent_id: str | None = scope.get(AGENT_ID_STATE_KEY)
        token = _current_agent.set(agent_id)
        try:
            await self.app(scope, receive, send)
        finally:
            _current_agent.reset(token)


def _require_agent_id() -> str:
    aid = _current_agent.get()
    if aid is None:
        raise RuntimeError("agent_id is missing — auth middleware not applied?")
    return aid


def build_mcp(config: Config) -> FastMCP:
    """Build a FastMCP instance with the five coord_* tools registered."""
    mcp = FastMCP(
        "asquared_mcp",
        # OriginAllowlistMiddleware owns the host/origin policy so Claude Web's
        # hosted connector can use rotating Origin values through the tunnel.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @mcp.tool(
        name="coord_post",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def coord_post(
        params: CoordPostInput,
        ctx: Context,  # type: ignore[type-arg]
    ) -> dict[str, Any]:
        """Post a message to the coordination queue.

        The `kind` field determines routing and notification behavior:
        - 'stop_and_ask': any recipient -> high-priority Pushover push
        - 'handoff' / 'task_complete' / 'question': only when to_agent='alex'
          -> normal-priority push
        - 'status' / 'note' / 'answer': no push

        Returns: { message_id, from_agent, notified, notification_error }
        """
        from_agent = _require_agent_id()
        msg_id = post_message(
            db_path=config.server.db_path,
            from_agent=from_agent,
            to_agent=params.to_agent,
            kind=params.kind,
            payload=json.dumps(params.payload),
            thread_id=params.thread_id,
        )
        result = await maybe_notify(config, msg_id)
        return {
            "message_id": msg_id,
            "from_agent": from_agent,
            "notified": result.notified,
            "notification_reason": result.reason,
            "notification_error": result.error,
        }

    @mcp.tool(
        name="coord_read",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def coord_read(
        params: CoordReadInput,
        ctx: Context,  # type: ignore[type-arg]
    ) -> dict[str, Any]:
        """Read the shared coordination queue.

        The `to_agent` field is a routing hint, not an access-control boundary:
        authenticated agents can read direct, Alex-addressed, and broadcast
        messages. Defaults: most recent 50 messages. Use `since_id` to poll for
        new ones. Use `thread_id` to read a single thread, `kinds` to filter,
        `unread_only` to skip messages your agent has already acked.
        """
        agent_id = _require_agent_id()
        rows = read_messages(
            db_path=config.server.db_path,
            to_agent=None,
            since_id=params.since_id,
            thread_id=params.thread_id,
            kinds=params.kinds,
            unread_only=params.unread_only,
            limit=params.limit,
            read_by_agent=agent_id,
        )
        return {
            "messages": [_row_to_dict(r) for r in rows],
            "count": len(rows),
        }

    @mcp.tool(
        name="coord_threads",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def coord_threads_tool(
        params: CoordThreadsInput,
        ctx: Context,  # type: ignore[type-arg]
    ) -> dict[str, Any]:
        """Manage coordination threads: create, list, or close a coordination thread."""
        agent_id = _require_agent_id()
        if params.action == "create":
            if not params.title:
                raise ValueError("`title` is required for action='create'")
            tid = create_thread(config.server.db_path, params.title, created_by=agent_id)
            return {"thread_id": tid, "title": params.title}
        if params.action == "list":
            rows = list_threads(config.server.db_path, include_closed=params.include_closed)
            return {"threads": [dict(r) for r in rows]}
        if params.action == "close":
            if not params.thread_id:
                raise ValueError("`thread_id` is required for action='close'")
            close_thread(config.server.db_path, params.thread_id)
            return {"closed": params.thread_id}
        raise ValueError(f"unknown action: {params.action}")

    @mcp.tool(
        name="coord_ack",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def coord_ack(
        params: CoordAckInput,
        ctx: Context,  # type: ignore[type-arg]
    ) -> dict[str, Any]:
        """Mark messages as read by your agent ID."""
        agent_id = _require_agent_id()
        n = ack_messages(config.server.db_path, params.message_ids, by_agent=agent_id)
        return {"acked": n}

    @mcp.tool(
        name="coord_status",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def coord_status(
        params: CoordStatusInput,
        ctx: Context,  # type: ignore[type-arg]
    ) -> dict[str, Any]:
        """Post a lightweight status heartbeat to broadcast (no notification)."""
        from_agent = _require_agent_id()
        msg_id = post_message(
            db_path=config.server.db_path,
            from_agent=from_agent,
            to_agent="broadcast",
            kind="status",
            payload=json.dumps({"summary": params.summary}),
            thread_id=params.thread_id,
        )
        return {"message_id": msg_id, "from_agent": from_agent}

    return mcp


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    if d.get("read_by"):
        try:
            d["read_by"] = json.loads(d["read_by"])
        except json.JSONDecodeError:
            pass
    if d.get("payload"):
        try:
            d["payload"] = json.loads(d["payload"])
        except json.JSONDecodeError:
            pass
    return d


async def health(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "version": __version__})


def build_app(config: Config) -> Starlette:
    """Compose Starlette app: /health unauthenticated; /mcp wrapped in middleware."""
    init_db(config.server.db_path)
    mcp = build_mcp(config)
    mcp_asgi: ASGIApp = mcp.streamable_http_app()

    return Starlette(
        routes=[
            Route(HEALTH_PATH, health),
            *build_oauth_routes(config),
            Mount("/", app=mcp_asgi),
        ],
        middleware=[
            Middleware(OriginAllowlistMiddleware, allowed_origins=config.allowed_origins),
            Middleware(BearerTokenMiddleware, token_map=config.tokens, db_path=config.server.db_path),
            Middleware(AgentContextMiddleware),
        ],
        lifespan=lambda app: mcp.session_manager.run(),
    )


def main() -> None:
    """Entry point used by `asquared-mcp` script."""
    logging.basicConfig(
        level=os.environ.get("COORD_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config_path = os.environ.get("COORD_CONFIG", "./config.toml")
    config = load_config(config_path)
    app = build_app(config)
    # Bind to 0.0.0.0 inside the container — docker-compose maps to 127.0.0.1
    # so the host-side socket is not internet-reachable. Cloudflared connects
    # via the loopback mapping.
    uvicorn.run(app, host="0.0.0.0", port=config.server.port)


if __name__ == "__main__":
    main()
