from typing import Any

from pikvm_mcp.client import PiKVMClient


class RecordingClient(PiKVMClient):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []
        self.contents: list[str | None] = []

    def request(self, method: str, path: str, *, params: dict[str, Any] | None = None, content: str | None = None) -> Any:
        self.calls.append((method, path, params))
        self.contents.append(content)
        return {}


def test_press_key_releases_non_modifier_key():
    client = RecordingClient()

    client.press_key("Enter")

    assert client.calls == [
        ("POST", "/api/hid/events/send_key", {"key": "Enter", "state": "true", "finish": "true"})
    ]


def test_relative_mouse_and_wheel_use_fixed_api_paths():
    client = RecordingClient()

    client.move_mouse_relative(25, -10)
    client.scroll_mouse(0, -3)

    assert client.calls == [
        ("POST", "/api/hid/events/send_mouse_relative", {"delta_x": 25, "delta_y": -10}),
        ("POST", "/api/hid/events/send_mouse_wheel", {"delta_x": 0, "delta_y": -3}),
    ]


def test_type_text_uses_default_pikvm_keymap_without_an_empty_parameter():
    client = RecordingClient()

    client.type_text("echo hello world")

    assert client.calls == [("POST", "/api/hid/print", None)]
    assert client.contents == ["echo hello world"]


def test_mount_media_disconnects_selects_read_only_cdrom_then_connects():
    client = RecordingClient()

    client.mount_media("rescue.iso")

    assert client.calls == [
        ("POST", "/api/msd/set_connected", {"connected": "false"}),
        ("POST", "/api/msd/set_params", {"image": "rescue.iso", "cdrom": "true", "rw": "false"}),
        ("POST", "/api/msd/set_connected", {"connected": "true"}),
    ]
