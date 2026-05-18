"""FastMCP server with bearer-auth + origin-validated streamable HTTP transport."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sqlite3
from contextvars import ContextVar
from pathlib import Path
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
from .inventory_client import InventoryClient
from .inventory_tools import register_inventory_tools
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


SERVER_INSTRUCTIONS = """\
ASquaredMCP — coordination + home-inventory tools for the asquaredhome.com homelab.

Two tool families share this server:

- coord_* : inter-agent coordination across Claude Web, Claude Code, Codex.
  Use coord_post to message another agent; coord_read to pick up your queue;
  coord_threads to scope work; coord_ack to mark messages read; coord_status
  for lightweight broadcast heartbeats.

- inventory_* : read-only access to the home-inventory app (rooms, items,
  photos, documents, floor plans). Use inventory_list_locations to find a
  place by name, inventory_list_location_items to see what's there,
  inventory_search_items for free-text catalog search, inventory_get_item
  for full detail on one row, and inventory_get_location_map for floor
  plans with marker coordinates. May be absent on deployments without
  home-inventory configured.

For a fuller overview, read the resource at docs://asquared-mcp/readme.
"""


SERVER_README = """\
# ASquaredMCP

Coordination + home-inventory MCP server hosted at
`https://mcp.asquaredhome.com`. Bearer-token auth; one bearer per agent.

## Tool families

### coord_* — inter-agent coordination

- `coord_post` — post a message addressed to another agent (or `broadcast`).
  Kinds: `stop_and_ask` (high-priority Pushover), `handoff` / `task_complete`
  / `question` (normal-priority push when addressed to `alex`), `status` /
  `note` / `answer` (no push).
- `coord_read` — read the queue. `since_id` polls for new; `thread_id`
  scopes to a thread; `unread_only` skips already-acked messages.
- `coord_threads` — create / list / close coordination threads.
- `coord_ack` — mark messages read by your agent.
- `coord_status` — broadcast a lightweight heartbeat (no notification).

### inventory_* — home-inventory read access

- `inventory_search_items` — full-text search the item catalog.
- `inventory_get_item` — fetch one item by UUID or HI-XXXX reference id.
- `inventory_list_locations` — enumerate Locations (floors, rooms, racks).
- `inventory_list_location_items` — items physically in a Location.
- `inventory_get_location_map` — floor-plan map with marker coordinates.

The inventory family is read-only in v1. Writes (`create_item`, etc.)
live behind a future opt-in flag.

## Auth

Static bearer tokens keyed to agent ids (`claude-web`, `claude-code`,
`codex`) in the server config. OAuth client-credentials flow available
for hosted connectors (Claude Web's MCP connector, ChatGPT, etc.); see
the OAuth discovery endpoints under `/.well-known/`.

## Out of band

- Pushover for high-priority pages.
- Home-inventory API at `https://inventory.asquaredhome.com/mcp-api/*`
  (server-to-server bearer route bypassing oauth2-proxy).
"""


def _server_readme_text() -> str:
    """README content exposed as an MCP resource.

    Returns the in-repo SERVER_README constant so the resource lives
    inside the binary and survives container rebuilds without a volume
    mount. An external README.md at the repo root may diverge over time
    — this constant is the one the LLM sees.
    """

    return SERVER_README

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


def build_mcp(
    config: Config,
    *,
    inventory_client: InventoryClient | None = None,
) -> FastMCP:
    """Build a FastMCP instance with the coord_* (and optionally inventory_*) tools.

    ``inventory_client`` is the dependency seam for tests: production
    callers leave it None and ``build_app`` constructs one from
    ``config.home_inventory``; tests inject a transport-stubbed client.
    """

    mcp = FastMCP(
        "asquared_mcp",
        # MCP spec 2025-06-18 InitializeResult.instructions: the client
        # forwards this string to the LLM as system context so the model
        # can pick the right tool family up front.
        instructions=SERVER_INSTRUCTIONS,
        # OriginAllowlistMiddleware owns the host/origin policy so Claude Web's
        # hosted connector can use rotating Origin values through the tunnel.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @mcp.resource(
        "docs://asquared-mcp/readme",
        name="server_readme",
        title="ASquaredMCP server overview",
        description=(
            "Capability overview for ASquaredMCP — both tool families, "
            "auth posture, and out-of-band integrations. Audience: humans + "
            "agents needing more than the initialize instructions provide."
        ),
        mime_type="text/markdown",
    )
    async def server_readme() -> str:
        return _server_readme_text()

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

    # Register inventory_* family only when home-inventory is wired up.
    # Deployments that don't run home-inventory keep a working coord-only
    # server; deployments that do get five extra read-only tools.
    if inventory_client is not None:
        register_inventory_tools(mcp, inventory_client)

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


def _build_inventory_client(config: Config) -> InventoryClient | None:
    """Construct an InventoryClient if [home_inventory] is configured.

    Returns None when ``base_url`` or ``token`` is blank, in which case
    build_mcp skips registering the inventory tool family entirely.
    """

    hi = config.home_inventory
    if not hi.base_url or not hi.token:
        return None
    return InventoryClient(
        base_url=hi.base_url,
        token=hi.token,
        timeout_seconds=hi.timeout_seconds,
    )


def build_app(config: Config) -> Starlette:
    """Compose Starlette app: /health unauthenticated; /mcp wrapped in middleware."""
    init_db(config.server.db_path)
    inventory_client = _build_inventory_client(config)
    mcp = build_mcp(config, inventory_client=inventory_client)
    mcp_asgi: ASGIApp = mcp.streamable_http_app()

    @contextlib.asynccontextmanager
    async def _lifespan(_app: Starlette):
        # The session manager owns the streamable-HTTP transport. Combine
        # it with the inventory client's aclose() so an httpx pool isn't
        # leaked across reloads.
        async with mcp.session_manager.run():
            try:
                yield
            finally:
                if inventory_client is not None:
                    await inventory_client.aclose()

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
        lifespan=_lifespan,
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
