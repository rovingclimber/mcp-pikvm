# PiKVM MCP

Control one PiKVM from an MCP client such as ChatGPT Codex or Google Antigravity. It can view and crop the screen, read on-screen text, navigate BIOS, type, mount an ISO already stored on PiKVM, and operate power controls — but it is not a remote shell.

## Choose one Compose file

| File | Use it when | What is exposed |
| --- | --- | --- |
| `compose.yaml` | **Recommended.** You have a DNS name and Cloudflare DNS. | Only Traefik on HTTPS (port 443) and its HTTP redirect (port 80). MCP itself is private inside Docker. |
| `compose-http.yaml` | You explicitly trust your LAN and do not want HTTPS. | MCP directly on port 8000, protected by bearer token and a CIDR client-network allow-list. |

Do not run both files together.

## The three keys

| Key | Where it lives | What it allows |
| --- | --- | --- |
| Bearer token | The Compose file | Connecting to MCP and reading PiKVM status. |
| View token | Generated on container start; shown in Docker logs | Capturing a screen image. |
| Control token | Generated on container start; shown in Docker logs | Keyboard, mouse, ISO and power actions. |

View and control tokens are replaced whenever the PiKVM MCP container restarts. An old chat therefore loses screen/control authority after a restart. Docker logs are sensitive while those tokens are valid.

If the PiKVM URL, user, or password are incomplete, MCP exposes only `pikvm_info` and explains what needs configuring.

## Recommended: HTTPS with Cloudflare DNS-01

You need a DNS name such as `mcp.example.com`, a Cloudflare API token scoped to that zone with **Zone / Zone / Read** and **Zone / DNS / Edit**, and Docker Compose on the server/LXC.

On the Docker host:

```sh
mkdir mcp-pikvm && cd mcp-pikvm
curl -fsSLO https://raw.githubusercontent.com/rovingclimber/mcp-pikvm/v0.9.0/compose.yaml
```

Open `compose.yaml` and replace every `CHANGE ME` value. In particular:

1. Add the PiKVM URL, username and password.
2. Replace all `mcp.example.com` occurrences with your DNS name, including `MCP_PUBLIC_ENDPOINT`.
3. Change the Traefik `ipallowlist` CIDR to your own LAN, for example `192.168.1.0/24`.
4. Add the Cloudflare token and certificate-notification email.

Generate and insert a bearer token without printing it:

```sh
TOKEN="$(openssl rand -base64 32 | tr -d '\n')" && sed -i "s|MCP_HTTP_BEARER_TOKEN: \"CHANGE-ME-USE-A-LONG-RANDOM-TOKEN\"|MCP_HTTP_BEARER_TOKEN: \"$TOKEN\"|" compose.yaml && unset TOKEN
```

Then start it:

```sh
docker compose up -d
docker compose logs pikvm-mcp
```

The second command displays the exact MCP endpoint and the temporary view/control tokens. The HTTPS endpoint normally looks like:

```text
https://mcp.example.com/mcp
```

The MCP service has **no published port** in this file. `127.0.0.1` is not involved: Traefik reaches MCP through Docker's private service network, and only Traefik publishes ports 80/443.

Traefik obtains and renews the certificate using Cloudflare DNS-01. It has a read-only Docker socket only to discover the labelled MCP service; the MCP container itself has no Docker socket access. [Traefik’s ACME documentation](https://doc.traefik.io/traefik/reference/install-configuration/tls/certificate-resolvers/acme/)

## Fallback: trusted-LAN HTTP

Use this only when every network between your client and the Docker host is trusted. It is normal HTTP, so the bearer token travels unencrypted.

```sh
mkdir mcp-pikvm && cd mcp-pikvm
curl -fsSLO https://raw.githubusercontent.com/rovingclimber/mcp-pikvm/v0.9.0/compose-http.yaml
```

Edit the marked values, then generate the bearer token:

```sh
TOKEN="$(openssl rand -base64 32 | tr -d '\n')" && sed -i "s|MCP_HTTP_BEARER_TOKEN: \"CHANGE-ME-USE-A-LONG-RANDOM-TOKEN\"|MCP_HTTP_BEARER_TOKEN: \"$TOKEN\"|" compose-http.yaml && unset TOKEN
docker compose -f compose-http.yaml up -d
```

Set `MCP_HTTP_ALLOWED_HOSTS` to the Docker host’s actual LAN address, for example `192.168.1.139:8000`. It is an HTTP **Host** allow-list, so it must not contain CIDR values.

Set `MCP_HTTP_ALLOWED_CLIENT_NETWORKS` to who may connect. It accepts CIDR ranges, for example:

```text
192.168.0.0/24
192.168.0.0/24,10.0.0.0/8
192.168.1.0/24,fd00::/8
```

The HTTP file publishes `8000:8000`, meaning Docker listens on the host’s network interfaces. The CIDR gate is enforced by MCP as a second check; use your host firewall as well if it has more than one network.

The endpoint is:

```text
http://your-docker-host:8000/mcp
```

## Connect ChatGPT Codex on Windows

First set the bearer token as a Windows user environment variable. Copy the `MCP_HTTP_BEARER_TOKEN` value from your Compose file, then run this in PowerShell:

```powershell
[Environment]::SetEnvironmentVariable('PIKVM_MCP_BEARER_TOKEN', 'paste-the-bearer-token-here', 'User')
```

Completely close and reopen ChatGPT Desktop after setting it.

### Use the desktop UI

In ChatGPT Desktop, go to **File → Settings → Plugins → MCPs → Add server**. Enter:

- **URL:** `https://mcp.example.com/mcp` — or the trusted-LAN HTTP endpoint.
- **Bearer token env var:** `PIKVM_MCP_BEARER_TOKEN`

The bearer token stays in your Windows user environment rather than in the UI configuration.

### Or edit Codex configuration directly

Add this to `%USERPROFILE%\.codex\config.toml` (for example `C:\Users\Justin\.codex\config.toml`):

```toml
[mcp_servers.mcp-pikvm]
enabled = true
url = "https://mcp.example.com/mcp"
bearer_token_env_var = "PIKVM_MCP_BEARER_TOKEN"
```

For an HTTP-only LAN deployment, change only the URL. Codex supports streamable HTTP servers with `url` and `bearer_token_env_var`; personal settings belong in `~/.codex/config.toml`, while trusted projects may use `.codex/config.toml`. [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-basic), [MCP configuration](https://learn.chatgpt.com/docs/extend/mcp)

Start a new task and type `/mcp` to check the connection. Codex receives the tool names and safety guidance automatically. Begin with `pikvm_status`; it needs only the bearer token. Give the view/control token only when you explicitly want screen access or control.

## Connect Google Antigravity

Antigravity’s remote-MCP configuration uses static HTTP headers. Its documented `env` object is for a local **stdio** server process, not for substituting values into headers of a remote `serverUrl`; there is no documented environment-variable reference for this bearer header. That means the bearer token is stored in the JSON file below, so keep that file private. [Antigravity MCP documentation](https://antigravity.google/docs/mcp)

Put this in your Antigravity MCP configuration file (commonly `%USERPROFILE%\.gemini\config\mcp_config.json`; use the location shown by your installed Antigravity build):

```json
{
  "mcpServers": {
    "mcp-pikvm": {
      "serverUrl": "https://mcp.example.com/mcp",
      "headers": {
        "Authorization": "Bearer paste-the-bearer-token-here"
      },
      "requiresOAuth": false
    }
  }
}
```

Use your HTTP endpoint instead only for a trusted LAN. Restart Antigravity after saving the file.

## Operating safely

- `pikvm_status` is bearer-only and read-only.
- `pikvm_screenshot`, `pikvm_screenshot_region`, and on-demand `pikvm_read_screen_text` require the current view token. OCR is local, runs only when requested, caps its working image at roughly 1.2 megapixels, and never needs a GPU.
- Keyboard, mouse, ISO mounting/ejection, HID changes and ATX power controls require the current control token. Destructive operations also require clear confirmation text.
- For desktop work use **absolute** mouse mode and a fresh screenshot before coordinate actions. `pikvm_move_pointer`, `pikvm_click_screen`, `pikvm_double_click_screen`, and `pikvm_drag_screen` use that screenshot ID; dragging requires `CONFIRM DRAG` and always releases the left button if movement fails. For BIOS/UEFI use **relative** mouse mode plus `pikvm_move_mouse_relative` and `pikvm_click_mouse`.

To revoke view/control authority immediately, restart the MCP service:

```sh
docker compose restart pikvm-mcp
```

The server deliberately does not offer arbitrary shell execution, PiKVM configuration changes, arbitrary PiKVM API calls, or media upload/download.

## Moving from v0.5 or older

v0.7 removes the admin page, runtime configuration, `secrets/` directory, setup script, and `.env` file. Make a fresh deployment directory using **one** Compose file above, update the Windows bearer-token environment variable, then stop the old service before starting the new one.

## Reusable PiKVM API core

This repository also contains `pikvm_core`: a reusable authenticated PiKVM API
client with no MCP or LLM dependency. The public MCP uses it, while a future
trusted local runtime can import it directly. Its full-API transport and
integration boundary are documented in [PiKVM Core](docs/pikvm-core.md).

## Development

```sh
uv sync --group dev
uv run pytest
```
