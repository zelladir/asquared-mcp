# Claude Web Connector Setup

Claude Web (claude.ai) supports custom remote MCP connectors via your account settings.

## Steps

1. In Claude Web, navigate to **Settings → Connectors → Add Custom Connector**.
2. Fill in:
   - **Name:** `asquared`
   - **URL:** `https://mcp.asquaredhome.com/mcp`
   - **Authentication:** Bearer token
   - **Token:** `<CLAUDE_WEB_TOKEN>` (from `config.toml`)
3. Save. Toggle the connector on for the chats where you want it (or set it
   as always-on).

## Verify

Start a new chat:

> **You:** What tools do you have available from asquared?

Expected: `coord_post`, `coord_read`, `coord_threads`, `coord_ack`, `coord_status`.

The server accepts Claude Web's hosted connector through the public tunnel host
(`mcp.asquaredhome.com`) even if the connector sends a rotating Origin header.

## Important: Claude Web cannot autonomously poll

Claude Web only sees `coord_*` tool results when you actively chat. If Codex
posts a STOP-AND-ASK at midnight and Claude Web is needed to resolve, the loop is:

1. Pushover notifies Alex's phone.
2. Alex starts a chat with Claude Web.
3. Claude Web reads the queue.
4. Alex relays the response back through Claude Web.

This is by design. Notifications go to a phone, not to a chat session.
