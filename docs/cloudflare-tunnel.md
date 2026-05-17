# Cloudflare Tunnel Setup

The coordination server runs locally and is exposed at `https://mcp.asquaredhome.com`
via Cloudflare Tunnel. No port forwarding, no firewall changes. DNS for
`asquaredhome.com` is already managed by Cloudflare.

This doc is for Alex to follow on the workstation that hosts the server.
Verify each `cloudflared` command against `cloudflared --help` before running —
flags shift between point releases.

> **Note on naming:** the Cloudflare Tunnel itself is named `pfit-coord` in the
> existing deployment. That's a Cloudflare-internal label (no end user sees it —
> only the public hostname `mcp.asquaredhome.com` matters). The repo and Python
> package were renamed to `asquared-mcp` / `asquared_mcp`, but the tunnel name
> stays for the existing deployment to avoid a separate dashboard migration.
> Fresh deployments may choose any tunnel name they like; just keep
> `mcp.asquaredhome.com` (or your own subdomain) wired to it.

## Prerequisites

- `cloudflared` CLI installed:
  - **Windows:** download from <https://github.com/cloudflare/cloudflared/releases>
  - **macOS:** `brew install cloudflare/cloudflare/cloudflared`
  - **Linux:** see the GitHub releases page for the package matching your distro.
- A Cloudflare account with `asquaredhome.com` already on the dashboard.

## One-time setup

### 1. Authenticate

```bash
cloudflared tunnel login
```

A browser window opens; pick `asquaredhome.com`. A cert is written to
`~/.cloudflared/cert.pem` (Windows: `%USERPROFILE%\.cloudflared\cert.pem`).

### 2. Create the tunnel

```bash
cloudflared tunnel create pfit-coord
```

Returns a tunnel ID and writes credentials to
`~/.cloudflared/<tunnel-id>.json`. Note the ID — you need it in the config below.

### 3. Route DNS

```bash
cloudflared tunnel route dns pfit-coord mcp.asquaredhome.com
```

Adds a CNAME in Cloudflare DNS pointing `mcp.asquaredhome.com` to the tunnel.

### 4. Write the config file

Create `~/.cloudflared/config.yml`:

```yaml
tunnel: pfit-coord
credentials-file: /Users/<you>/.cloudflared/<tunnel-id>.json   # absolute path
# Windows example:
# credentials-file: C:\Users\<you>\.cloudflared\<tunnel-id>.json

ingress:
  - hostname: mcp.asquaredhome.com
    service: http://localhost:8765
    originRequest:
      connectTimeout: 30s
      # MCP streamable HTTP uses long-lived SSE responses for streaming tool
      # results. Keep chunked encoding ON (the default) so SSE flushes through.
      disableChunkedEncoding: false
  - service: http_status:404
```

## Running

### Foreground (debugging)

```bash
make tunnel
# or directly:
cloudflared tunnel run pfit-coord
```

### Background as a system service

```bash
# macOS/Linux:
sudo cloudflared service install
sudo systemctl enable --now cloudflared    # Linux
# macOS uses launchd via the install command above.

# Windows:
cloudflared service install
```

## Verification

```bash
# Reaches the server via the tunnel; auth required, so 401 is correct:
curl -i https://mcp.asquaredhome.com/mcp
# Expect: HTTP/2 401

# Health bypasses auth:
curl https://mcp.asquaredhome.com/health
# Expect: {"status": "ok", "version": "0.1.0"}
```

## Stopping

- Service: `sudo cloudflared service uninstall` (or `cloudflared service uninstall` on Windows)
- Foreground: Ctrl-C

## Notes

- Cloudflare Tunnel custom hostnames on a domain you own are free.
- SSE / long-lived HTTP work through tunnels by default. The `originRequest`
  block above sets a generous connect timeout to avoid premature disconnects.
- When `cloudflared` restarts, in-flight long-lived connections drop — clients
  reconnect automatically per MCP spec resumability rules.
