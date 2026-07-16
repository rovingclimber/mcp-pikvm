from __future__ import annotations

import hmac
import hashlib
import base64
import logging
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ImageContent, TextContent
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from .audit import audit, content_fingerprint
from .client import PiKVMClient
from .config import HttpSettings, Settings
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


_http_host, _http_port, _http_path = _listener_settings()
mcp = FastMCP("PiKVM Local", instructions=(
    "This is a local-only PiKVM bridge. Inspect status before control operations. "
    "Never enable or use control without the operator's explicit instruction."
), host=_http_host, port=_http_port, streamable_http_path=_http_path)

_settings: Settings | None = None
_control_token: str | None = None
_control_until = 0.0


@dataclass(frozen=True)
class Snapshot:
    identifier: str
    captured_at: float


_latest_snapshot: Snapshot | None = None

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
    global _settings
    if _settings is None:
        _settings = Settings.from_environment()
    return _settings


def _client() -> PiKVMClient:
    return PiKVMClient(_settings_or_error())


def _safe_error(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, (ConfigurationError, httpx.HTTPError, RuntimeError, PermissionError, ValueError)):
        return {"ok": False, "error": str(exc)}
    logging.exception("Unexpected PiKVM MCP error")
    return {"ok": False, "error": "Unexpected server error; inspect the local audit log."}


def _require_control(token: str) -> Settings:
    settings = _settings_or_error()
    if not _control_token or time.monotonic() >= _control_until:
        raise PermissionError("Control is not armed or the control lease has expired.")
    if not hmac.compare_digest(token, _control_token):
        raise PermissionError("Invalid control token.")
    return settings


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
def pikvm_status() -> dict[str, Any]:
    """Read PiKVM system, ATX, HID, and virtual-media status. Does not control the target PC."""
    try:
        settings = _settings_or_error()
        result = _client().status()
        audit("status_read", {}, settings.audit_log)
        return {"ok": True, "result": result}
    except Exception as exc:
        return _safe_error(exc)


@mcp.tool()
def pikvm_screenshot() -> CallToolResult:
    """Capture and return the current PiKVM screen as a JPEG image. Requires screen capture to be explicitly enabled in server configuration."""
    global _latest_snapshot
    try:
        settings = _settings_or_error()
        if not settings.screen_capture_enabled:
            raise PermissionError("Screen capture is disabled. Set PIKVM_MCP_SCREEN_CAPTURE_ENABLED=1 to allow it.")
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


@mcp.tool()
def pikvm_enable_control(operator_secret: str) -> dict[str, Any]:
    """Arm time-limited control after an operator supplies the out-of-band control secret."""
    global _control_token, _control_until
    try:
        settings = _settings_or_error()
        if not settings.control_secret:
            raise PermissionError("Control is disabled: PIKVM_MCP_CONTROL_SECRET is not configured.")
        if not hmac.compare_digest(operator_secret, settings.control_secret):
            raise PermissionError("Control secret was rejected.")
        _control_token = secrets.token_urlsafe(32)
        _control_until = time.monotonic() + settings.control_ttl_seconds
        audit("control_armed", {"ttl_seconds": settings.control_ttl_seconds}, settings.audit_log)
        return {"ok": True, "control_token": _control_token, "expires_in_seconds": settings.control_ttl_seconds}
    except Exception as exc:
        return _safe_error(exc)


@mcp.tool()
def pikvm_disable_control() -> dict[str, Any]:
    """Immediately revoke the active control lease. Safe to call at any time."""
    global _control_token, _control_until
    _control_token = None
    _control_until = 0.0
    try:
        settings = _settings_or_error()
        audit("control_revoked", {}, settings.audit_log)
    except Exception:
        # Revocation is still successful if PiKVM configuration was never completed.
        pass
    return {"ok": True, "message": "Control lease revoked."}


@mcp.tool()
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


@mcp.tool()
def pikvm_type_text(text: str, control_token: str) -> dict[str, Any]:
    """Type a short, single-line text string on the target PC. Requires an active control lease."""
    try:
        if not text or len(text) > 512 or "\n" in text or "\r" in text:
            raise ValueError("Text must be a non-empty single line of at most 512 characters.")
        settings = _require_control(control_token)
        result = _client().type_text(text)
        audit("text_typed", {"length": len(text), "sha256_prefix": content_fingerprint(text)}, settings.audit_log)
        return {"ok": True, "result": result}
    except Exception as exc:
        return _safe_error(exc)


@mcp.tool()
def pikvm_send_shortcut(keys: list[str], control_token: str) -> dict[str, Any]:
    """Send a 1-4 key PiKVM shortcut, such as [ControlLeft, AltLeft, Delete]. Requires an active control lease."""
    try:
        if not 1 <= len(keys) <= 4 or any(key not in _ALLOWED_KEY_NAMES for key in keys):
            raise ValueError("Use one to four supported PiKVM web key names.")
        settings = _require_control(control_token)
        result = _client().send_shortcut(keys)
        audit("shortcut_sent", {"keys": keys}, settings.audit_log)
        return {"ok": True, "result": result}
    except Exception as exc:
        return _safe_error(exc)


@mcp.tool()
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
        hid_x = _normalised_to_hid(x)
        hid_y = _normalised_to_hid(y)
        client = _client()
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


def main() -> None:
    transport = os.getenv("MCP_TRANSPORT", "streamable-http").strip().lower()
    if transport == "stdio":
        mcp.run(transport="stdio")
        return
    if transport != "streamable-http":
        raise ConfigurationError("MCP_TRANSPORT must be stdio or streamable-http.")

    settings = HttpSettings.from_environment()
    # The MCP SDK performs Host validation before protocol handling. A missing
    # Origin is allowed for native clients; any browser Origin needs an exact
    # explicit allow-list entry in addition to the bearer token.
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=settings.allowed_hosts,
        allowed_origins=settings.allowed_origins,
    )
    app = mcp.streamable_http_app()
    app = OriginAllowlistMiddleware(BearerTokenMiddleware(app, settings.bearer_token), settings.allowed_origins)

    import uvicorn

    uvicorn.run(app, host=_http_host, port=_http_port, log_level="info")


if __name__ == "__main__":
    main()
