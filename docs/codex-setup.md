# Codex Setup

The Codex CLI's MCP config location varies by version. Run `codex --help` or
check the official docs to confirm the correct file. As of writing the file is
typically `~/.codex/mcp.json` or under `~/.config/codex/`.

## 1. Add the MCP server

```json
{
  "mcpServers": {
    "asquared": {
      "url": "https://mcp.asquaredhome.com/mcp",
      "headers": {
        "Authorization": "Bearer <CODEX_TOKEN>"
      }
    }
  }
}
```

Replace `<CODEX_TOKEN>` with the token from your local `config.toml`
mapped to `codex`.

## 2. Verify

In a Codex session:

> **You:** Read the coord queue.

Expected: Codex calls `coord_read` and returns whatever messages are
addressed to `codex` (or `broadcast`).

## 3. First message

> **You:** Use coord_post to send a stop_and_ask to alex with the question "test ping".

Within ~30 seconds Alex's phone should receive a Pushover notification with:
- Title: `[codex] stop_and_ask`
- Body: `test ping`
- Priority: high (bypasses quiet hours)
