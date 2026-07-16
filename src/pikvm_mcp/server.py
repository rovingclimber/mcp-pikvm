from __future__ import annotations

import hmac
import hashlib
import base64
from ipaddress import ip_address
import logging
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ImageContent, TextContent
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from .audit import audit, content_fingerprint
from .client import PiKVMClient
from .config import HttpSettings, Settings, pikvm_is_configured
from .security import ConfigurationError

logging.basicConfig(level=logging.INFO, format="%(message)s")


class BearerTokenMiddleware:
    """Require a deployment-local bearer secret for every HTTP MCP request."""

    def __init__(self, app: Any, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope["headers"]}
        authorization = headers.get("authorization", "")
        valid = authorization.startswith("Bearer ") and hmac.compare_digest(
            authorization[7:], self.token
        )
        if not valid:
            response = JSONResponse(
                {"error": "authentication_required"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


class OriginAllowlistMiddleware:
    """Reject browser-originated requests unless their Origin is explicitly allowed."""

    def __init__(self, app: Any, allowed_origins: list[str]) -> None:
        self.app = app
        self.allowed_origins = set(allowed_origins)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope["headers"]}
            origin = headers.get("origin")
            if origin and origin not in self.allowed_origins:
                response = JSONResponse({"error": "origin_not_allowed"}, status_code=403)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


class ClientNetworkMiddleware:
    """Optionally restrict direct HTTP clients to private CIDR ranges."""

    def __init__(self, app: Any, allowed_networks: list[Any]) -> None:
        self.app = app
        self.allowed_networks = allowed_networks

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http" and self.allowed_networks:
            client = scope.get("client")
            host = client[0] if client else None
            try:
                allowed = bool(host) and any(ip_address(host) in network for network in self.allowed_networks)
            except ValueError:
                allowed = False
            if not allowed:
                response = JSONResponse({"error": "client_network_not_allowed"}, status_code=403)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def _listener_settings() -> tuple[str, int, str]:
    host = os.getenv("MCP_HOST", "127.0.0.1").strip()
    path = os.getenv("MCP_STREAMABLE_HTTP_PATH", "/mcp").strip()
    try:
        port = int(os.getenv("MCP_PORT", "8000"))
    except ValueError as exc:
        raise ConfigurationError("MCP_PORT must be an integer.") from exc
    if not host or not 1 <= port <= 65535:
        raise ConfigurationError("MCP_HOST must be set and MCP_PORT must be between 1 and 65535.")
    if not path.startswith("/") or path == "/" or "?" in path or "#" in path:
        raise ConfigurationError("MCP_STREAMABLE_HTTP_PATH must be a non-root absolute path.")
    return host, port, path


def _public_endpoint(path: str) -> str | None:
    """Return the operator-facing endpoint for startup logs, if configured."""
    value = os.getenv("MCP_PUBLIC_ENDPOINT", "").strip().rstrip("/")
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.fragment:
        raise ConfigurationError("MCP_PUBLIC_ENDPOINT must be an absolute HTTP(S) URL without query or fragment.")
    if parsed.path != path:
        raise ConfigurationError("MCP_PUBLIC_ENDPOINT must use the same path as MCP_STREAMABLE_HTTP_PATH.")
    return value


_http_host, _http_port, _http_path = _listener_settings()
_public_endpoint_url = _public_endpoint(_http_path)
mcp = FastMCP("PiKVM Local", instructions=(
    "This is a local-only PiKVM bridge. Inspect status before control operations and inspect HID status "
    "before diagnosing input. Never use the view or control token without the operator's explicit instruction. "
    "Use discrete key presses for BIOS navigation; switch to relative mouse mode for BIOS/UEFI only when asked."
), host=_http_host, port=_http_port, streamable_http_path=_http_path)

_configured = pikvm_is_configured()
_view_token = secrets.token_urlsafe(32)
_control_token = secrets.token_urlsafe(32)
if _configured:
    logging.warning("PiKVM MCP view token (sensitive; replaced on restart): %s", _view_token)
    logging.warning("PiKVM MCP control token (sensitive; replaced on restart): %s", _control_token)


@dataclass(frozen=True)
class Snapshot:
    identifier: str
    captured_at: float


_latest_snapshot: Snapshot | None = None

_MAX_TYPED_LINE_LENGTH = 512
_MAX_TYPED_LINES = 32
_MAX_TYPED_BATCH_LENGTH = 4096

_ALLOWED_KEY_NAMES = {
    "AltLeft", "AltRight", "ArrowDown", "ArrowLeft", "ArrowRight", "ArrowUp", "Backspace",
    "CapsLock", "ContextMenu", "ControlLeft", "ControlRight", "Delete", "End", "Enter", "Escape",
    "Home", "Insert", "MetaLeft", "MetaRight", "PageDown", "PageUp", "Pause", "PrintScreen",
    "ScrollLock", "ShiftLeft", "ShiftRight", "Space", "Tab",
    *(f"F{number}" for number in range(1, 13)),
    *(f"Key{letter}" for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
    *(f"Digit{number}" for number in range(10)),
}


def _settings_or_error() -> Settings:
    if not _configured:
        raise ConfigurationError("PiKVM is not configured. Set PIKVM_URL, PIKVM_USERNAME, and PIKVM_PASSWORD in .env, then restart the container.")
    return Settings.from_environment()


def _client() -> PiKVMClient:
    return PiKVMClient(_settings_or_error())


def _safe_error(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, (ConfigurationError, httpx.HTTPError, RuntimeError, PermissionError, ValueError)):
        return {"ok": False, "error": str(exc)}
    logging.exception("Unexpected PiKVM MCP error")
    return {"ok": False, "error": "Unexpected server error; inspect the local audit log."}


def _require_control(token: str) -> Settings:
    settings = _settings_or_error()
    if not hmac.compare_digest(token, _control_token):
        raise PermissionError("Invalid control token. Use the token printed when this container most recently started.")
    return settings


def _require_view(token: str) -> Settings:
    settings = _settings_or_error()
    if not hmac.compare_digest(token, _view_token):
        raise PermissionError("Invalid view token. Use the token printed when this container most recently started.")
    return settings


def _tool() -> Any:
    """Do not advertise PiKVM operations until the container is configured."""
    def register(function: Any) -> Any:
        return mcp.tool()(function) if _configured else function
    return register


def _normalised_to_hid(value: float) -> int:
    """Map a screenshot coordinate in [0,1] to PiKVM's centre-origin HID range."""
    if not 0.0 <= value <= 1.0:
        raise ValueError("Coordinates must be normalized values from 0.0 to 1.0.")
    return round((value * 2.0 - 1.0) * 32767)


def _require_fresh_snapshot(snapshot_id: str, settings: Settings) -> None:
    if not _latest_snapshot or not hmac.compare_digest(snapshot_id, _latest_snapshot.identifier):
        raise PermissionError("The screenshot ID is unknown. Capture a fresh screenshot before clicking.")
    if time.monotonic() - _latest_snapshot.captured_at > settings.screenshot_ttl_seconds:
        raise PermissionError("The screenshot is stale. Capture a new screenshot before clicking.")


def _image_error(exc: Exception) -> CallToolResult:
    error = _safe_error(exc)["error"]
    return CallToolResult(content=[TextContent(type="text", text=error)], isError=True)


@mcp.tool()
def pikvm_info() -> dict[str, Any]:
    """Explain this PiKVM MCP server and whether the Docker container is ready to use."""
    if not _configured:
        return {
            "ok": False,
            "configured": False,
            "message": (
                "This PiKVM MCP container is not configured. Set PIKVM_URL, PIKVM_USERNAME, "
                "and PIKVM_PASSWORD in its .env file, then run docker compose up -d. "
                "After restart, reconnect this MCP client to see the PiKVM tools."
            ),
        }
    return {
        "ok": True,
        "configured": True,
        "message": (
            "Bearer access permits status only. Supply the fresh view token from the container startup "
            "logs for screenshots, or the fresh control token for keyboard, mouse, media, and power actions. "
            "Both tokens are replaced whenever the container restarts."
        ),
    }


@_tool()
def pikvm_status() -> dict[str, Any]:
    """Read PiKVM system, ATX, HID, and virtual-media status. Does not control the target PC."""
    try:
        settings = _settings_or_error()
        result = _client().status()
        audit("status_read", {}, settings.audit_log)
        return {"ok": True, "result": result}
    except Exception as exc:
        return _safe_error(exc)


@_tool()
def pikvm_screenshot(view_token: str) -> CallToolResult:
    """Capture and return the current PiKVM screen as a JPEG image. Requires the fresh view token printed in container startup logs."""
    global _latest_snapshot
    try:
        settings = _require_view(view_token)
        image = _client().snapshot()
        identifier = hashlib.sha256(image).hexdigest()[:20]
        _latest_snapshot = Snapshot(identifier=identifier, captured_at=time.monotonic())
        audit("screenshot_captured", {"bytes": len(image), "snapshot_id": identifier}, settings.audit_log)
        return CallToolResult(content=[
            TextContent(
                type="text",
                text=(
                    f"Screenshot ID: {identifier}. It expires for click authorization in "
                    f"{settings.screenshot_ttl_seconds} seconds."
                ),
            ),
            ImageContent(type="image", data=base64.b64encode(image).decode("ascii"), mimeType="image/jpeg"),
        ])
    except Exception as exc:
        return _image_error(exc)


@_tool()
def pikvm_atx_power(action: str, control_token: str, confirmation: str) -> dict[str, Any]:
    """Change PC power state. action: on, off, off_hard, reset_hard. Confirmation must exactly name the action."""
    try:
        if action not in {"on", "off", "off_hard", "reset_hard"}:
            raise ValueError("Unsupported ATX action.")
        if confirmation != f"CONFIRM {action}":
            raise PermissionError(f"Confirmation must be exactly: CONFIRM {action}")
        settings = _require_control(control_token)
        result = _client().atx_action(action)
        audit("atx_action", {"action": action}, settings.audit_log)
        return {"ok": True, "result": result}
    except Exception as exc:
        return _safe_error(exc)


@_tool()
def pikvm_type_text(text: str, control_token: str, press_enter: bool = False) -> dict[str, Any]:
    """Type a short single-line string using PiKVM's text endpoint. Set press_enter=true only when the operator wants the command submitted."""
    try:
        if not text or len(text) > _MAX_TYPED_LINE_LENGTH or "\n" in text or "\r" in text:
            raise ValueError(f"Text must be a non-empty single line of at most {_MAX_TYPED_LINE_LENGTH} characters.")
        settings = _require_control(control_token)
        result = _client().type_text(text)
        if press_enter:
            _client().press_key("Enter")
        audit(
            "text_typed",
            {"length": len(text), "sha256_prefix": content_fingerprint(text), "press_enter": press_enter},
            settings.audit_log,
        )
        return {"ok": True, "result": result}
    except Exception as exc:
        return _safe_error(exc)


@_tool()
def pikvm_type_lines(lines: list[str], control_token: str, confirmation: str) -> dict[str, Any]:
    """Type and submit a small multi-line script one line at a time. Every line gets Enter. Maximum 32 lines / 4096 characters; requires exact CONFIRM TYPE <count> LINES."""
    try:
        if not 1 <= len(lines) <= _MAX_TYPED_LINES:
            raise ValueError(f"Provide between 1 and {_MAX_TYPED_LINES} lines.")
        if any(not line or "\n" in line or "\r" in line or len(line) > _MAX_TYPED_LINE_LENGTH for line in lines):
            raise ValueError(f"Each line must be non-empty, single-line, and at most {_MAX_TYPED_LINE_LENGTH} characters.")
        total_length = sum(len(line) for line in lines)
        if total_length > _MAX_TYPED_BATCH_LENGTH:
            raise ValueError(f"The combined line length must be at most {_MAX_TYPED_BATCH_LENGTH} characters.")
        expected = f"CONFIRM TYPE {len(lines)} LINES"
        if confirmation != expected:
            raise PermissionError(f"Confirmation must be exactly: {expected}")
        settings = _require_control(control_token)
        client = _client()
        for line in lines:
            client.type_text(line)
            client.press_key("Enter")
        audit("text_lines_typed", {"count": len(lines), "length": total_length}, settings.audit_log)
        return {"ok": True, "lines_submitted": len(lines)}
    except Exception as exc:
        return _safe_error(exc)


@_tool()
def pikvm_press_key(key: str, control_token: str) -> dict[str, Any]:
    """Press and release one named PiKVM HID key, such as Enter, Escape, ArrowDown, F2, or Delete. Prefer this for BIOS/UEFI navigation."""
    try:
        if key not in _ALLOWED_KEY_NAMES:
            raise ValueError("Use a supported PiKVM web key name.")
        settings = _require_control(control_token)
        result = _client().press_key(key)
        audit("key_pressed", {"key": key}, settings.audit_log)
        return {"ok": True, "result": result}
    except Exception as exc:
        return _safe_error(exc)


@_tool()
def pikvm_send_shortcut(keys: list[str], control_token: str) -> dict[str, Any]:
    """Send a 1-4 key PiKVM shortcut, such as [ControlLeft, AltLeft, Delete]. Requires the fresh control token."""
    try:
        if not 1 <= len(keys) <= 4 or any(key not in _ALLOWED_KEY_NAMES for key in keys):
            raise ValueError("Use one to four supported PiKVM web key names.")
        settings = _require_control(control_token)
        result = _client().send_shortcut(keys)
        audit("shortcut_sent", {"keys": keys}, settings.audit_log)
        return {"ok": True, "result": result}
    except Exception as exc:
        return _safe_error(exc)


@_tool()
def pikvm_set_hid_connection(connected: bool, control_token: str, confirmation: str) -> dict[str, Any]:
    """Connect or disconnect PiKVM keyboard/mouse USB HID. Use when HID status says offline. Confirmation: CONFIRM HID CONNECT or CONFIRM HID DISCONNECT."""
    try:
        expected = "CONFIRM HID CONNECT" if connected else "CONFIRM HID DISCONNECT"
        if confirmation != expected:
            raise PermissionError(f"Confirmation must be exactly: {expected}")
        settings = _require_control(control_token)
        result = _client().set_hid_connected(connected)
        audit("hid_connection_changed", {"connected": connected}, settings.audit_log)
        return {"ok": True, "result": result}
    except Exception as exc:
        return _safe_error(exc)


@_tool()
def pikvm_reset_hid(control_token: str, confirmation: str) -> dict[str, Any]:
    """Release/reset PiKVM HID devices when a key or mouse button may be stuck. Requires confirmation CONFIRM HID RESET."""
    try:
        if confirmation != "CONFIRM HID RESET":
            raise PermissionError("Confirmation must be exactly: CONFIRM HID RESET")
        settings = _require_control(control_token)
        result = _client().reset_hid()
        audit("hid_reset", {}, settings.audit_log)
        return {"ok": True, "result": result}
    except Exception as exc:
        return _safe_error(exc)


@_tool()
def pikvm_set_mouse_mode(mode: str, control_token: str, confirmation: str) -> dict[str, Any]:
    """Switch PiKVM mouse between absolute (desktop) and relative (BIOS/UEFI) mode. Requires confirmation CONFIRM MOUSE MODE <mode>."""
    try:
        if mode not in {"absolute", "relative"}:
            raise ValueError("Mouse mode must be absolute or relative.")
        expected = f"CONFIRM MOUSE MODE {mode}"
        if confirmation != expected:
            raise PermissionError(f"Confirmation must be exactly: {expected}")
        settings = _require_control(control_token)
        result = _client().set_mouse_mode(mode)
        audit("mouse_mode_changed", {"mode": mode}, settings.audit_log)
        return {"ok": True, "result": result}
    except Exception as exc:
        return _safe_error(exc)


@_tool()
def pikvm_move_mouse_relative(delta_x: int, delta_y: int, control_token: str) -> dict[str, Any]:
    """Move the relative mouse by a small offset for BIOS/UEFI. Use after selecting relative mouse mode; each delta must be from -2000 to 2000."""
    try:
        if not -2000 <= delta_x <= 2000 or not -2000 <= delta_y <= 2000:
            raise ValueError("Relative mouse deltas must each be between -2000 and 2000.")
        settings = _require_control(control_token)
        result = _client().move_mouse_relative(delta_x, delta_y)
        audit("mouse_moved_relative", {"delta_x": delta_x, "delta_y": delta_y}, settings.audit_log)
        return {"ok": True, "result": result}
    except Exception as exc:
        return _safe_error(exc)


@_tool()
def pikvm_click_mouse(button: str, control_token: str) -> dict[str, Any]:
    """Click left, middle, or right mouse button at the current cursor position. Useful in relative mouse mode."""
    try:
        if button not in {"left", "middle", "right"}:
            raise ValueError("Mouse button must be left, middle, or right.")
        settings = _require_control(control_token)
        client = _client()
        client.set_mouse_button(button, True)
        result = client.set_mouse_button(button, False)
        audit("mouse_clicked", {"button": button}, settings.audit_log)
        return {"ok": True, "result": result}
    except Exception as exc:
        return _safe_error(exc)


@_tool()
def pikvm_double_click_mouse(button: str, control_token: str) -> dict[str, Any]:
    """Double-click left, middle, or right mouse button at its current position. Useful with relative mouse mode."""
    try:
        if button not in {"left", "middle", "right"}:
            raise ValueError("Mouse button must be left, middle, or right.")
        settings = _require_control(control_token)
        client = _client()
        for _ in range(2):
            client.set_mouse_button(button, True)
            client.set_mouse_button(button, False)
            time.sleep(0.1)
        audit("mouse_double_clicked", {"button": button}, settings.audit_log)
        return {"ok": True}
    except Exception as exc:
        return _safe_error(exc)


@_tool()
def pikvm_scroll_mouse(delta_y: int, control_token: str) -> dict[str, Any]:
    """Scroll the current view using a signed wheel delta from -100 to 100. Positive/negative direction depends on the target OS."""
    try:
        if not -100 <= delta_y <= 100:
            raise ValueError("Mouse wheel delta must be between -100 and 100.")
        settings = _require_control(control_token)
        result = _client().scroll_mouse(0, delta_y)
        audit("mouse_scrolled", {"delta_y": delta_y}, settings.audit_log)
        return {"ok": True, "result": result}
    except Exception as exc:
        return _safe_error(exc)


@_tool()
def pikvm_list_iso_images() -> dict[str, Any]:
    """List ISO images already stored on this PiKVM and the virtual-media drive state. This is read-only; use before mounting an ISO."""
    try:
        settings = _settings_or_error()
        result = _client().media_status()
        storage = result.get("storage", {}) if isinstance(result, dict) else {}
        images = storage.get("images", {}) if isinstance(storage, dict) else {}
        if not isinstance(images, dict):
            images = {}
        iso_images = {name: details for name, details in images.items() if isinstance(name, str) and name.lower().endswith(".iso")}
        audit("iso_images_listed", {"count": len(iso_images)}, settings.audit_log)
        return {
            "ok": True,
            "images": iso_images,
            "drive": result.get("drive", {}) if isinstance(result, dict) else {},
        }
    except Exception as exc:
        return _safe_error(exc)


@_tool()
def pikvm_mount_iso(image: str, control_token: str, confirmation: str) -> dict[str, Any]:
    """Mount an ISO already listed by pikvm_list_iso_images as a read-only virtual CD-ROM. Requires exact confirmation CONFIRM MOUNT <image>."""
    try:
        if not image or not image.lower().endswith(".iso"):
            raise ValueError("Only a previously listed .iso image can be mounted.")
        expected = f"CONFIRM MOUNT {image}"
        if confirmation != expected:
            raise PermissionError(f"Confirmation must be exactly: {expected}")
        settings = _require_control(control_token)
        media = _client().media_status()
        storage = media.get("storage", {}) if isinstance(media, dict) else {}
        images = storage.get("images", {}) if isinstance(storage, dict) else {}
        if not isinstance(images, dict) or image not in images:
            raise ValueError("The ISO is not currently available on this PiKVM. List ISO images again before mounting.")
        result = _client().mount_media(image)
        audit("iso_mounted", {"image": image}, settings.audit_log)
        return {"ok": True, "result": result, "image": image}
    except Exception as exc:
        return _safe_error(exc)


@_tool()
def pikvm_eject_media(control_token: str, confirmation: str) -> dict[str, Any]:
    """Disconnect the currently mounted PiKVM virtual CD/DVD or USB image from the target PC. Requires confirmation CONFIRM EJECT MEDIA."""
    try:
        if confirmation != "CONFIRM EJECT MEDIA":
            raise PermissionError("Confirmation must be exactly: CONFIRM EJECT MEDIA")
        settings = _require_control(control_token)
        result = _client().eject_media()
        audit("media_ejected", {}, settings.audit_log)
        return {"ok": True, "result": result}
    except Exception as exc:
        return _safe_error(exc)


@_tool()
def pikvm_click_screen(
    x: float,
    y: float,
    screenshot_id: str,
    control_token: str,
    confirmation: str,
) -> dict[str, Any]:
    """Click a fresh screenshot at normalized coordinates (0=left/top, 1=right/bottom). Requires an active lease and CONFIRM CLICK."""
    try:
        if confirmation != "CONFIRM CLICK":
            raise PermissionError("Confirmation must be exactly: CONFIRM CLICK")
        settings = _require_control(control_token)
        _require_fresh_snapshot(screenshot_id, settings)
        client = _client()
        hid = client.request("GET", "/api/hid")
        mouse = hid.get("mouse", {}) if isinstance(hid, dict) else {}
        if isinstance(mouse, dict) and mouse.get("absolute") is False:
            raise PermissionError("Screenshot-coordinate clicks require absolute mouse mode. Switch to absolute or use relative mouse movement and click tools.")
        hid_x = _normalised_to_hid(x)
        hid_y = _normalised_to_hid(y)
        client.move_mouse_absolute(hid_x, hid_y)
        time.sleep(0.075)
        client.set_mouse_button("left", True)
        client.set_mouse_button("left", False)
        audit(
            "screen_clicked",
            {"snapshot_id": screenshot_id, "x": round(x, 4), "y": round(y, 4)},
            settings.audit_log,
        )
        return {"ok": True, "result": {"hid_x": hid_x, "hid_y": hid_y}}
    except Exception as exc:
        return _safe_error(exc)


@_tool()
def pikvm_double_click_screen(
    x: float,
    y: float,
    screenshot_id: str,
    control_token: str,
    confirmation: str,
) -> dict[str, Any]:
    """Double-click a fresh screenshot at normalized coordinates in absolute mouse mode. Requires CONFIRM DOUBLE CLICK and a fresh screenshot."""
    try:
        if confirmation != "CONFIRM DOUBLE CLICK":
            raise PermissionError("Confirmation must be exactly: CONFIRM DOUBLE CLICK")
        settings = _require_control(control_token)
        _require_fresh_snapshot(screenshot_id, settings)
        client = _client()
        hid = client.request("GET", "/api/hid")
        mouse = hid.get("mouse", {}) if isinstance(hid, dict) else {}
        if isinstance(mouse, dict) and mouse.get("absolute") is False:
            raise PermissionError("Screenshot-coordinate clicks require absolute mouse mode. Switch to absolute or use relative mouse movement and click tools.")
        hid_x = _normalised_to_hid(x)
        hid_y = _normalised_to_hid(y)
        client.move_mouse_absolute(hid_x, hid_y)
        time.sleep(0.075)
        for _ in range(2):
            client.set_mouse_button("left", True)
            client.set_mouse_button("left", False)
            time.sleep(0.1)
        audit(
            "screen_double_clicked",
            {"snapshot_id": screenshot_id, "x": round(x, 4), "y": round(y, 4)},
            settings.audit_log,
        )
        return {"ok": True, "result": {"hid_x": hid_x, "hid_y": hid_y}}
    except Exception as exc:
        return _safe_error(exc)


def main() -> None:
    transport = os.getenv("MCP_TRANSPORT", "streamable-http").strip().lower()
    if transport == "stdio":
        mcp.run(transport="stdio")
        return
    if transport != "streamable-http":
        raise ConfigurationError("MCP_TRANSPORT must be stdio or streamable-http.")

    settings = HttpSettings.from_environment()
    if _public_endpoint_url:
        logging.warning("PiKVM MCP endpoint: %s", _public_endpoint_url)
    # The MCP SDK performs Host validation before protocol handling. A missing
    # Origin is allowed for native clients; any browser Origin needs an exact
    # explicit allow-list entry in addition to the bearer token.
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=settings.allowed_hosts,
        allowed_origins=settings.allowed_origins,
    )
    app = mcp.streamable_http_app()
    app = ClientNetworkMiddleware(
        OriginAllowlistMiddleware(BearerTokenMiddleware(app, settings.bearer_token), settings.allowed_origins),
        settings.allowed_client_networks,
    )

    import uvicorn

    uvicorn.run(app, host=_http_host, port=_http_port, log_level="info")


if __name__ == "__main__":
    main()
