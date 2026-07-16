from __future__ import annotations

from typing import Any

import httpx

from .config import Settings


class PiKVMClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def request(self, method: str, path: str, *, params: dict[str, Any] | None = None, content: str | None = None) -> Any:
        # Paths are constants in this program, never supplied by the MCP client.
        with httpx.Client(
            base_url=self.settings.base_url,
            auth=(self.settings.username, self.settings.password),
            verify=self.settings.tls_verify,
            timeout=httpx.Timeout(10.0, connect=5.0),
            follow_redirects=False,
            headers={
                "Accept": "application/json",
                **({"Content-Type": "text/plain; charset=utf-8"} if content is not None else {}),
            },
        ) as client:
            response = client.request(method, path, params=params, content=content)
            response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise RuntimeError("PiKVM returned an unsuccessful API response.")
        return payload.get("result", {})

    def snapshot(self) -> bytes:
        """Fetch a single JPEG frame; this intentionally does not use a streaming endpoint."""
        with httpx.Client(
            base_url=self.settings.base_url,
            auth=(self.settings.username, self.settings.password),
            verify=self.settings.tls_verify,
            timeout=httpx.Timeout(15.0, connect=5.0),
            follow_redirects=False,
            headers={"Accept": "image/jpeg"},
        ) as client:
            response = client.get("/api/streamer/snapshot")
            response.raise_for_status()
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type != "image/jpeg":
            raise RuntimeError("PiKVM snapshot response was not a JPEG image.")
        if not response.content or len(response.content) > 8 * 1024 * 1024:
            raise RuntimeError("PiKVM snapshot is empty or exceeds the 8 MiB safety limit.")
        return response.content

    def status(self) -> dict[str, Any]:
        return {
            "system": self.request("GET", "/api/info"),
            "atx": self.request("GET", "/api/atx"),
            "hid": self.request("GET", "/api/hid"),
            "msd": self.request("GET", "/api/msd"),
        }

    def atx_action(self, action: str) -> Any:
        return self.request("POST", "/api/atx/power", params={"action": action, "wait": "true"})

    def type_text(self, text: str) -> Any:
        return self.request("POST", "/api/hid/print", params={"keymap": ""}, content=text)

    def send_shortcut(self, keys: list[str]) -> Any:
        return self.request("POST", "/api/hid/events/send_shortcut", params={"keys": ",".join(keys)})

    def press_key(self, key: str) -> Any:
        """Press and release one named PiKVM HID key without leaving it stuck."""
        return self.request(
            "POST",
            "/api/hid/events/send_key",
            params={"key": key, "state": "true", "finish": "true"},
        )

    def set_hid_connected(self, connected: bool) -> Any:
        return self.request("POST", "/api/hid/set_connected", params={"connected": str(connected).lower()})

    def reset_hid(self) -> Any:
        return self.request("POST", "/api/hid/reset")

    def set_mouse_mode(self, mode: str) -> Any:
        output = {"absolute": "usb", "relative": "usb_rel"}[mode]
        return self.request("POST", "/api/hid/set_params", params={"mouse_output": output})

    def move_mouse_absolute(self, to_x: int, to_y: int) -> Any:
        return self.request("POST", "/api/hid/events/send_mouse_move", params={"to_x": to_x, "to_y": to_y})

    def move_mouse_relative(self, delta_x: int, delta_y: int) -> Any:
        return self.request(
            "POST",
            "/api/hid/events/send_mouse_relative",
            params={"delta_x": delta_x, "delta_y": delta_y},
        )

    def set_mouse_button(self, button: str, state: bool) -> Any:
        return self.request(
            "POST",
            "/api/hid/events/send_mouse_button",
            params={"button": button, "state": str(state).lower()},
        )

    def scroll_mouse(self, delta_x: int, delta_y: int) -> Any:
        return self.request(
            "POST",
            "/api/hid/events/send_mouse_wheel",
            params={"delta_x": delta_x, "delta_y": delta_y},
        )

    def media_status(self) -> Any:
        return self.request("GET", "/api/msd")

    def mount_media(self, image: str) -> Any:
        self.request("POST", "/api/msd/set_connected", params={"connected": "false"})
        self.request("POST", "/api/msd/set_params", params={"image": image, "cdrom": "true", "rw": "false"})
        return self.request("POST", "/api/msd/set_connected", params={"connected": "true"})

    def eject_media(self) -> Any:
        return self.request("POST", "/api/msd/set_connected", params={"connected": "false"})
