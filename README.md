# PiKVM MCP

A safety-first [Model Context Protocol](https://modelcontextprotocol.io/) server for one PiKVM. The Docker image serves Streamable HTTP at `/mcp`, with optional local stdio support.

Published images: `rovingclimber/mcp-pikvm`. Use a fixed release tag in production; `latest` tracks the newest tagged release.

## Safety model

- HTTP MCP requires a separate bearer token; anonymous network access is not supported.
- Host and Origin validation protect the endpoint. Native MCP clients normally omit `Origin`; browser origins must be explicitly allowed.
- The base Compose file publishes only `127.0.0.1:8000`.
- The PiKVM must be on a private/link-local/loopback network by default; redirects, arbitrary API paths, and public PiKVM addresses are rejected.
- PiKVM HTTPS and certificate verification are enabled by default.
- Control requires a separate operator secret, a short-lived control token, and additional confirmations for power and click actions.
- Audit records exclude passwords, bearer tokens, control secrets, and typed text.

## Easy Docker Compose setup

Download the setup script, inspect it, then run it. It downloads the Compose files, prompts for the PiKVM password without echoing it, generates independent bearer and control secrets, and stores them in an owner-only `mcp-pikvm/secrets` directory. Do **not** pipe downloaded scripts directly into `sh`.

```sh
curl -fsSLO https://raw.githubusercontent.com/rovingclimber/mcp-pikvm/v0.2.2/scripts/setup-docker-compose.sh
less setup-docker-compose.sh
sh setup-docker-compose.sh
```

For a local-only deployment:

```sh
cd mcp-pikvm
docker compose up -d
```

If Codex runs on the same Docker host, connect to `http://127.0.0.1:8000/mcp`. If Codex runs on another machine, choose either Caddy HTTPS or the explicit trusted-LAN option in the setup script; it prints the correct endpoint. Read the bearer token from `secrets/mcp_http_bearer_token.txt`; keep that file private.

The base [`compose.yaml`](compose.yaml) is a complete local-only example. To configure manually, copy the `.example` files in [`secrets/`](secrets/), remove the suffix, populate them, and keep the resulting files private. They are ignored by Git and mounted as Docker secrets rather than baked into the image.

## Optional public HTTPS with Caddy

The setup script can configure the optional [`compose.https.yaml`](compose.https.yaml) overlay. It starts Caddy as a reverse proxy: Caddy is the only service exposed to ports 80 and 443; the PiKVM MCP service remains on its private Docker network and its loopback port.

Choose `y` when the script asks about Caddy HTTPS, give it a public DNS name, point that name's A/AAAA record at the host, and allow inbound TCP 80 and 443. Then start:

```sh
cd mcp-pikvm
docker compose -f compose.yaml -f compose.https.yaml up -d
```

Caddy obtains and renews the certificate and redirects HTTP to HTTPS automatically. Keep `MCP_HTTP_ALLOWED_ORIGINS` empty for native MCP clients; add exact HTTPS origins only if browser clients are intended. [Caddy automatic HTTPS requirements](https://caddyserver.com/docs/automatic-https)

The bearer-token gate is appropriate for a controlled private deployment. For an internet-facing or multi-user service, add an identity-aware proxy or OAuth provider and restrict access at the network layer.

## Connect Codex

Keep the bearer token out of command lines and committed configuration:

```sh
export PIKVM_MCP_BEARER_TOKEN="$(cat secrets/mcp_http_bearer_token.txt)"
codex mcp add pikvm-local --url https://mcp.example.net/mcp \
  --bearer-token-env-var PIKVM_MCP_BEARER_TOKEN
```

Replace the example URL with the endpoint printed by setup. `127.0.0.1` only works when Codex and Docker run on the same host. For a Windows Codex client connecting to an LXC, use the Caddy HTTPS URL (recommended) or the explicitly enabled trusted-LAN HTTP URL. Reload or start a new Codex task after changing MCP configuration.

## Optional stdio mode

For a client that launches the container directly without any listener:

```sh
docker run --rm -i --env-file .env -e MCP_TRANSPORT=stdio rovingclimber/mcp-pikvm:latest
```

## Control and screen workflow

1. Read `pikvm_status` first.
2. An operator supplies the separately stored `PIKVM_MCP_CONTROL_SECRET` to `pikvm_enable_control`.
3. Use the returned, short-lived control token for keyboard, mouse, and power operations.
4. Power actions require an exact matching confirmation; screen clicks require a fresh screenshot and `CONFIRM CLICK`.
5. Call `pikvm_disable_control` when finished.

Screens are disabled by default. Set `PIKVM_MCP_SCREEN_CAPTURE_ENABLED=1` only when a connected client should receive screen content. `pikvm_screenshot` returns JPEG content directly through MCP; `pikvm_click_screen` translates normalized screenshot coordinates into PiKVM absolute HID coordinates.

## Development

```sh
uv sync --group dev
uv run pytest
```

The server uses fixed PiKVM API paths and intentionally omits virtual-media uploads, arbitrary API calls, configuration changes, and shell access. See the [PiKVM API reference](https://docs.pikvm.org/api/) and [mouse documentation](https://docs.pikvm.org/mouse/).
