# Claude Code Setup

## 1. Add the MCP server to your Claude Code config

In your Claude Code MCP config (typical paths: `~/.claude/mcp.json` on macOS/Linux,
`%USERPROFILE%\.claude\mcp.json` on Windows — verify with `claude --help` if unsure):

```json
{
  "mcpServers": {
    "asquared": {
      "url": "https://mcp.asquaredhome.com/mcp",
      "headers": {
        "Authorization": "Bearer <CLAUDE_CODE_TOKEN>"
      }
    }
  }
}
```

Replace `<CLAUDE_CODE_TOKEN>` with the token from your local `config.toml`
mapped to `claude-code`.

## 2. Verify

In a Claude Code session:

> **You:** What MCP tools do you have available from asquared?

Expected: `coord_post`, `coord_read`, `coord_threads`, `coord_ack`, `coord_status`.

## 3. First message

> **You:** Use coord_status to broadcast that you're online.

Then verify from the host shell:

```bash
coord-cli read --as-agent broadcast
```

You should see a `status` message from `claude-code`.
