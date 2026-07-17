from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx


class PiKVMResponseError(RuntimeError):
    """Raised when PiKVM returns a transport or API-level error."""


@dataclass(frozen=True)
class PiKVMConnection:
    """Connection details owned by the caller's local configuration layer."""

    base_url: str
    username: str
    password: str
    tls_verify: bool | str = True
    timeout_seconds: float = 10.0


class PiKVMClient:
    """Complete low-level access to PiKVM's authenticated HTTP API.

    ``request`` is intentionally public: PiKVM versions and hardware models
    expose different documented endpoints. Higher-level applications should
    wrap it with typed operations and their own safety policy rather than
    inventing an arbitrary-path escape hatch of their own.
    """

    def __init__(self, connection: PiKVMConnection | Any) -> None:
        # Accept the MCP Settings object by structural compatibility during the
        # extraction transition. New consumers should use PiKVMConnection.
        self.connection = connection

    @property
    def _base_url(self) -> str:
        return self.connection.base_url

    def _client(self, *, accept: str = "application/json", timeout: float | None = None) -> httpx.Client:
        return httpx.Client(
            base_url=self._base_url,
            auth=(self.connection.username, self.connection.password),
            verify=self.connection.tls_verify,
            timeout=httpx.Timeout(timeout or getattr(self.connection, "timeout_seconds", 10.0), connect=5.0),
            follow_redirects=False,
            headers={"Accept": accept},
        )

    @staticmethod
    def _validate_path(path: str) -> None:
        if not path.startswith("/api/") or "?" in path or "#" in path:
            raise ValueError("PiKVM API paths must be absolute /api/ paths without query or fragment.")

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        content: str | bytes | None = None,
        files: dict[str, Any] | None = None,
    ) -> Any:
        """Call any PiKVM JSON API endpoint and return its ``result`` value."""
        self._validate_path(path)
        headers = {"Content-Type": "text/plain; charset=utf-8"} if isinstance(content, str) else {}
        with self._client() as client:
            response = client.request(method, path, params=params, content=content, files=files, headers=headers)
            response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise PiKVMResponseError("PiKVM returned a non-JSON response to a JSON API request.") from exc
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise PiKVMResponseError("PiKVM returned an unsuccessful API response.")
        return payload.get("result", {})

    def request_text(self, method: str, path: str, *, params: dict[str, Any] | None = None) -> str:
        """Call a documented PiKVM text endpoint such as ``/api/log``."""
        self._validate_path(path)
        with self._client(accept="text/plain") as client:
            response = client.request(method, path, params=params)
            response.raise_for_status()
        return response.text

    def request_bytes(self, method: str, path: str, *, params: dict[str, Any] | None = None, accept: str = "application/octet-stream") -> bytes:
        """Call a documented binary endpoint, for snapshots, video, or exports."""
        self._validate_path(path)
        with self._client(accept=accept, timeout=15.0) as client:
            response = client.request(method, path, params=params)
            response.raise_for_status()
        return response.content

    def stream_bytes(self, path: str, *, params: dict[str, Any] | None = None) -> Iterator[bytes]:
        """Yield chunks from a documented long-lived PiKVM binary stream."""
        self._validate_path(path)
        with self._client(timeout=30.0) as client, client.stream("GET", path, params=params) as response:
            response.raise_for_status()
            yield from response.iter_bytes()

    # Typed conveniences used by the public MCP and reusable by future backends.
    def snapshot(self) -> bytes:
        content = self.request_bytes("GET", "/api/streamer/snapshot", accept="image/jpeg")
        if not content or len(content) > 8 * 1024 * 1024:
            raise PiKVMResponseError("PiKVM snapshot is empty or exceeds the 8 MiB safety limit.")
        return content

    def status(self) -> dict[str, Any]:
        return {"system": self.request("GET", "/api/info"), "atx": self.request("GET", "/api/atx"), "hid": self.request("GET", "/api/hid"), "msd": self.request("GET", "/api/msd")}

    def atx_action(self, action: str) -> Any:
        return self.request("POST", "/api/atx/power", params={"action": action, "wait": "true"})

    def type_text(self, text: str) -> Any:
        return self.request("POST", "/api/hid/print", content=text)

    def send_shortcut(self, keys: list[str]) -> Any:
        return self.request("POST", "/api/hid/events/send_shortcut", params={"keys": ",".join(keys)})

    def press_key(self, key: str) -> Any:
        return self.request("POST", "/api/hid/events/send_key", params={"key": key, "state": "true", "finish": "true"})

    def set_hid_connected(self, connected: bool) -> Any:
        return self.request("POST", "/api/hid/set_connected", params={"connected": str(connected).lower()})

    def reset_hid(self) -> Any:
        return self.request("POST", "/api/hid/reset")

    def set_mouse_mode(self, mode: str) -> Any:
        return self.request("POST", "/api/hid/set_params", params={"mouse_output": {"absolute": "usb", "relative": "usb_rel"}[mode]})

    def move_mouse_absolute(self, to_x: int, to_y: int) -> Any:
        return self.request("POST", "/api/hid/events/send_mouse_move", params={"to_x": to_x, "to_y": to_y})

    def move_mouse_relative(self, delta_x: int, delta_y: int) -> Any:
        return self.request("POST", "/api/hid/events/send_mouse_relative", params={"delta_x": delta_x, "delta_y": delta_y})

    def set_mouse_button(self, button: str, state: bool) -> Any:
        return self.request("POST", "/api/hid/events/send_mouse_button", params={"button": button, "state": str(state).lower()})

    def scroll_mouse(self, delta_x: int, delta_y: int) -> Any:
        return self.request("POST", "/api/hid/events/send_mouse_wheel", params={"delta_x": delta_x, "delta_y": delta_y})

    def media_status(self) -> Any:
        return self.request("GET", "/api/msd")

    def mount_media(self, image: str) -> Any:
        # PiKVM returns MsdDisconnectedError when asked to disconnect an
        # already-disconnected drive. Query first so mounting works on both
        # strict and permissive PiKVM API versions.
        media = self.media_status()
        drive = media.get("drive", {}) if isinstance(media, dict) else {}
        if isinstance(drive, dict) and drive.get("connected") is True:
            self.request("POST", "/api/msd/set_connected", params={"connected": "false"})
        self.request("POST", "/api/msd/set_params", params={"image": image, "cdrom": "true", "rw": "false"})
        return self.request("POST", "/api/msd/set_connected", params={"connected": "true"})

    def eject_media(self) -> Any:
        return self.request("POST", "/api/msd/set_connected", params={"connected": "false"})
