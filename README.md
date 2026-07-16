# PiKVM MCP

A safety-first [Model Context Protocol](https://modelcontextprotocol.io/) server for one PiKVM. The Docker image uses **Streamable HTTP** at `/mcp`, the current standard transport for a remotely reachable MCP server. It also supports `stdio` for an entirely local client process.

The image is intended to be shareable; PiKVM credentials and control secrets are runtime configuration only and are never built into it.

Published images are available as `rovingclimber/mcp-pikvm`. Use a fixed release tag in a production deployment; `latest` tracks the newest tagged release.

## Safety model

- Streamable HTTP requires a separate bearer token of at least 32 characters. There is no anonymous network mode.
- Host validation and strict Origin validation protect the HTTP endpoint. Native MCP clients normally send no `Origin`; browser origins must be explicitly allowed.
- Docker Compose publishes only `127.0.0.1:8000` by default. For access from another device, put TLS and authentication boundary controls in front of it; do not expose port 8000 directly.
- PiKVM must be a private/link-local/loopback IP by default. Public addresses, redirects, arbitrary paths, and embedded URL credentials are rejected.
- HTTPS and certificate verification are on by default for the PiKVM connection.
- Control requires an out-of-band operator secret and a short-lived random control token. ATX and screen clicks require exact confirmations as well.
- Audit records exclude passwords, bearer tokens, control secrets, and typed text.

This is a guardrail, not a substitute for a management VLAN, a dedicated least-privilege PiKVM account, and a protected container host.

## Quick start with Docker Compose

Create local secret files. They are ignored by Git and mounted as Docker secrets, not added to the image or normal container environment.

```sh
mkdir -p secrets
cp secrets/pikvm-mcp.env.example secrets/pikvm-mcp.env
cp secrets/pikvm_password.txt.example secrets/pikvm_password.txt
cp secrets/pikvm_control_secret.txt.example secrets/pikvm_control_secret.txt
cp secrets/mcp_http_bearer_token.txt.example secrets/mcp_http_bearer_token.txt
chmod 600 secrets/pikvm-mcp.env secrets/*.txt
```

Set the PiKVM address and account in `secrets/pikvm-mcp.env`; set three independent, random values in the secret files. Generate the bearer token and control secret with a password manager or:

```sh
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Then build and start it:

```sh
docker compose up -d --build
```

The service is available to native local clients at `http://127.0.0.1:8000/mcp`. It requires the bearer token from `secrets/mcp_http_bearer_token.txt`.

For a direct container run, bind only to loopback and supply the same configuration and secret files:

```sh
docker build -t pikvm-local-mcp:latest .
docker run --rm -p 127.0.0.1:8000:8000 \
  --read-only --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  --cap-drop=ALL --security-opt=no-new-privileges \
  --env-file secrets/pikvm-mcp.env \
  -e PIKVM_PASSWORD_FILE=/run/secrets/pikvm_password \
  -e PIKVM_MCP_CONTROL_SECRET_FILE=/run/secrets/pikvm_control_secret \
  -e MCP_HTTP_BEARER_TOKEN_FILE=/run/secrets/mcp_http_bearer_token \
  -v "$PWD/secrets:/run/secrets:ro" pikvm-local-mcp:latest
```

To run a released image rather than building locally, use `rovingclimber/mcp-pikvm:<release-tag>` in the commands above. The GitHub workflow publishes tagged releases such as `v0.1.0` as `0.1.0` and updates `latest`.

## HTTPS and sharing the image

Streamable HTTP is the MCP transport. HTTPS is normally provided by a reverse proxy such as Caddy, Traefik, Nginx, or an organization’s ingress, rather than by baking certificates into this application container. The proxy should be the only service exposed to the network; it forwards to `pikvm-mcp:8000` on a private Docker network.

Before doing that:

1. Set `MCP_HTTP_ALLOWED_HOSTS` to the exact public host and port seen by the application, for example `mcp.example.net`.
2. Keep `MCP_HTTP_ALLOWED_ORIGINS` empty for native clients. If a browser client is genuinely required, add only its exact HTTPS origin, such as `https://console.example.net`.
3. Let the proxy terminate a trusted TLS certificate and do not publish the application’s port 8000.
4. Keep the bearer token in a secret manager or Docker/Kubernetes secret. Rotate it if the client or host is compromised.

[`deploy/Caddyfile.example`](deploy/Caddyfile.example) is a minimal upstream block for a Caddy deployment. It assumes the proxy and `pikvm-mcp` service share a private Docker network and that `MCP_PUBLIC_HOST` is a real DNS name.

The bearer-token gate is deliberately simple and suitable for a controlled private deployment. For an internet-facing or multi-user service, place it behind your organization’s identity-aware proxy or OAuth provider as well, and restrict access at the network layer.

## Connect Codex

For an HTTP MCP server, configure the URL and tell Codex which environment variable holds the bearer token; do not put the token in the command line or commit it to the MCP config.

```sh
export PIKVM_MCP_BEARER_TOKEN="$(cat secrets/mcp_http_bearer_token.txt)"
codex mcp add pikvm-local --url http://127.0.0.1:8000/mcp \
  --bearer-token-env-var PIKVM_MCP_BEARER_TOKEN
```

For an HTTPS deployment, substitute the trusted `https://…/mcp` URL. Reload or start a new Codex task after changing MCP configuration so it discovers the server’s tools.

## Optional stdio mode

`stdio` remains useful when the MCP client launches the container directly and no listener is wanted:

```sh
docker run --rm -i --env-file .env -e MCP_TRANSPORT=stdio pikvm-local-mcp:latest
```

In this mode no HTTP bearer token is needed. It is not the normal Docker distribution mode.

## Control and screen workflow

1. Read `pikvm_status` first.
2. To allow control, an operator supplies the separately stored `PIKVM_MCP_CONTROL_SECRET` to `pikvm_enable_control`.
3. The returned, short-lived control token is needed for keyboard, mouse, and power operations.
4. Power actions require an exact matching confirmation; screen clicks require a fresh screenshot and `CONFIRM CLICK`.
5. Call `pikvm_disable_control` when finished.

Screens are off by default. Set `PIKVM_MCP_SCREEN_CAPTURE_ENABLED=1` only when a connected client is intended to receive screen content. `pikvm_screenshot` returns JPEG content over MCP. `pikvm_click_screen` takes normalized screenshot coordinates and converts them to PiKVM’s absolute, center-origin HID range.

## Development

```sh
uv sync --group dev
uv run pytest
```

PiKVM API calls are constrained to fixed endpoints. This first version intentionally omits virtual-media uploads, arbitrary API calls, PiKVM configuration changes, and shell access. PiKVM’s documented endpoints and absolute-mouse behavior are in the [PiKVM API reference](https://docs.pikvm.org/api/) and [mouse documentation](https://docs.pikvm.org/mouse/).
