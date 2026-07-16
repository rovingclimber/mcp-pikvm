# PiKVM MCP

Control one PiKVM from an MCP client such as Codex. It is designed for the useful real-world jobs: seeing a remote screen, BIOS navigation, typing carefully, mounting an ISO already on the PiKVM, and power control — without turning the MCP into a general remote shell.

The image is `rovingclimber/mcp-pikvm`. The endpoint is `/mcp`.

## The simple security model

There are three separate keys. This is the important bit.

| Key | Where it lives | What it allows |
| --- | --- | --- |
| Bearer token | Your local `compose.yaml` | Connect to MCP and read PiKVM status. |
| View token | Generated when the container starts; shown in Docker logs | Capture a screen image. |
| Control token | Generated when the container starts; shown in Docker logs | Keyboard, mouse, ISO and power actions. |

The view and control tokens are fresh on every container restart. An old Codex task cannot keep screen or control authority after a restart. Docker logs are sensitive while those tokens are valid.

If `PIKVM_URL`, `PIKVM_USERNAME`, or `PIKVM_PASSWORD` are missing, the MCP server still starts but exposes **only** `pikvm_info`. It explains exactly what needs adding to `compose.yaml`. This is deliberate: a half-configured container cannot accidentally expose PiKVM functions.

## The recommended setup: HTTPS with Cloudflare DNS-01

This is the normal setup for a Windows PC running Codex and a Docker host/LXC elsewhere on your network. It gives your private MCP a normal, publicly trusted HTTPS certificate without opening ports merely to obtain the certificate.

Before starting, create a Cloudflare API token scoped only to the DNS zone used by your MCP hostname:

- `Zone / Zone / Read`
- `Zone / DNS / Edit`

Point a DNS record such as `mcp.example.com` at your Docker host's private address for your own network. The record need not be Internet-routable for DNS-01 validation.

Create an empty folder called `mcp-pikvm`, download the two annotated Compose files, and edit every value marked `CHANGE ME` **directly in those files**. Generate the MCP bearer value with `openssl rand -base64 32`.

```sh
mkdir mcp-pikvm && cd mcp-pikvm
curl -fsSLO https://raw.githubusercontent.com/rovingclimber/mcp-pikvm/v0.6.3/compose.yaml
curl -fsSLO https://raw.githubusercontent.com/rovingclimber/mcp-pikvm/v0.6.3/compose.https.yaml
```

[`compose.yaml`](compose.yaml) contains the PiKVM URL, username, password, bearer token, and comments explaining each value. [`compose.https.yaml`](compose.https.yaml) contains the Cloudflare token, certificate email, and the HTTPS hostname. Do not commit your edited copies: they contain credentials.

Then start it:

```sh
docker compose -f compose.yaml -f compose.https.yaml up -d
```

Traefik is the small companion container that obtains and renews the certificate. The PiKVM MCP container remains separate; it has no Docker socket access. Traefik needs a read-only Docker socket so it can route HTTPS traffic to this one service.

Get the two temporary operator tokens whenever you need them:

```sh
docker compose logs pikvm-mcp
```

Restarting revokes both immediately:

```sh
docker compose restart pikvm-mcp
```

## Connect Codex on Windows

The Docker host and Codex do **not** normally live on the same machine. Use the HTTPS address, not `127.0.0.1`:

```text
https://mcp.example.com/mcp
```

In PowerShell on the Windows PC, create a Windows-user environment variable holding the bearer token. If you can SSH to the Docker host, replace the host and path below with your own deployment:

```powershell
$token = 'paste the MCP_HTTP_BEARER_TOKEN value from compose.yaml here'
[Environment]::SetEnvironmentVariable('PIKVM_MCP_BEARER_TOKEN', $token, 'User')
Remove-Variable token
```

Then fully close and reopen Codex Desktop, and add the MCP connection:

```powershell
codex mcp add pikvm-lan --url "https://mcp.example.com/mcp" --bearer-token-env-var PIKVM_MCP_BEARER_TOKEN
codex mcp list
```

Start a **new task**. Type `/mcp` to check it is connected. Codex receives the tool names, descriptions, inputs, and the server's safety instructions automatically; no special prompt is needed.

For an operator-assisted task, retrieve the temporary view/control tokens from Docker logs and provide the appropriate one only when Codex asks for it. Start with `pikvm_status`, then use a view token for `pikvm_screenshot`. A control token is needed for every operation that changes the target.

## Trusted-LAN HTTP instead

Choose HTTP only for an intentionally trusted, segmented LAN. It listens on port 8000 and gives an address such as:

```text
http://192.168.1.139:8000/mcp
```

Use [`compose.yaml`](compose.yaml), edit its marked PiKVM and bearer values, change the published port to `0.0.0.0:8000:8000`, and set `MCP_HTTP_ALLOWED_HOSTS` to your intended LAN host. Then run:

```sh
docker compose up -d
```

## What the tools do

- `pikvm_info` explains readiness and the token model.
- `pikvm_status` reads PiKVM, HID, ATX and virtual-media state with bearer access only.
- `pikvm_screenshot` requires a view token; it returns an image and a short-lived screenshot ID.
- Keyboard, mouse, ISO mounting/ejection, HID connection and ATX tools require the control token. Power, mouse mode, media changes and screen-coordinate clicks also require clear confirmation text.

For desktop work use **absolute** mouse mode and a fresh screenshot before a coordinate click. For BIOS/UEFI use **relative** mouse mode, then `pikvm_move_mouse_relative` and `pikvm_click_mouse`. `pikvm_press_key` is more dependable than typed text in firmware screens.

The server never provides arbitrary shell execution, PiKVM configuration changes, arbitrary PiKVM API calls, or media uploads/downloads.

## Updating

Use a version tag rather than `latest` once you have a working deployment. To update later:

```sh
docker compose pull
docker compose up -d
```

Read the release notes first. Container restart means new view/control tokens, which is normally what you want.

### Moving from v0.5 or older

v0.6 is intentionally a clean break: it removes the admin page, encrypted runtime configuration, and `secrets/` directory. Do **not** pull the new image into an old Compose directory and expect it to retain those settings.

Instead, make a new deployment directory with the Compose files above, complete their marked values, update the bearer-token environment variable on the Codex computer, then stop the old service before starting the new one. The new container will create fresh view and control tokens on its first start.

## Development

```sh
uv sync --group dev
uv run pytest
```

See the [PiKVM API](https://docs.pikvm.org/api/) and [PiKVM mouse guide](https://docs.pikvm.org/mouse/) for the underlying device behaviour.
