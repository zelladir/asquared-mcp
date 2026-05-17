# Deployment Architecture

## Reference deployment

The reference deployment for `asquared-mcp` is:

- **Host:** Ubuntu 24 codeserver (always-on home-lab VM).
- **Public exposure:** Cloudflare Tunnel to `https://mcp.asquaredhome.com`.
  The tunnel terminates on the codeserver and forwards to `localhost:8765`
  inside the host's network namespace, which the docker-compose port mapping
  binds to the host on `0.0.0.0:8765`.
- **LAN exposure:** NPM (Nginx Proxy Manager) at `10.0.0.27` proxies
  `http://mcp.asquaredhome.com` to the codeserver at `10.0.1.35:8765`.
  Internal clients, such as Claude Code on the laptop within the home network,
  reach the server via the LAN path through Pi-hole's DNS override.

## Why `0.0.0.0:8765` and not `127.0.0.1:8765`?

The original repo intent was loopback-only binding to limit exposure to the
host machine. That assumption baked in a laptop-hosted deployment. The
codeserver-hosted reference deployment runs the reverse proxy and the tunnel
on a different host than the docker container, so loopback-only would prevent
both from reaching the service.

The bearer-token middleware is the access control. It applies regardless of
whether the LAN can reach port 8765 directly. Restricting LAN reachability
adds defense-in-depth, but at the cost of breaking the standard deployment
topology. The decision is to keep `0.0.0.0` and rely on the auth layer.

## Operational implications

- LAN clients can reach `http://10.0.1.35:8765/mcp` directly with a valid
  bearer token. This bypasses both NPM and the public tunnel.
- A compromised LAN host with a valid token has the same access as any other
  client. Treat the network as untrusted; treat tokens as secrets.
- Token rotation: edit `config.toml`, then `docker-compose restart coord-mcp`.

## Returning to laptop-hosted

If laptop-hosted becomes the deployment topology again:

1. The laptop's firewall typically blocks inbound LAN traffic by default, so
   `0.0.0.0` binding is functionally loopback-only on a normal laptop firewall
   configuration.
2. If stricter loopback enforcement is desired, edit `docker-compose.yml` to
   `127.0.0.1:8765:8765` for that deployment. Do not push that change back to
   `main`; it would break codeserver-hosted again.
