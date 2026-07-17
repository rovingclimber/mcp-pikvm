# PiKVM Core

`pikvm_core` is the reusable, transport-agnostic PiKVM API layer. It has no
MCP dependency, no agent policy, no control-token logic, and no LLM-facing
surface.

```python
from pikvm_core import PiKVMClient, PiKVMConnection

connection = PiKVMConnection(
    base_url="https://192.168.1.50",
    username="admin",
    password="local-secret",
)
client = PiKVMClient(connection)
state = client.request("GET", "/api/hid")
```

## API coverage contract

The core supports the complete authenticated PiKVM HTTP API from day one:

- `request()` for JSON API endpoints;
- `request_text()` for text endpoints such as system logs;
- `request_bytes()` for snapshots and other binary responses;
- `stream_bytes()` for documented long-lived binary streams;
- binary/form uploads through `request(..., files=...)`.

These methods validate that paths remain under `/api/`, but deliberately do
not impose MCP or agent safety policy. They are for trusted local software.

Typed convenience methods are maintained for the HID, ATX, snapshot and mass
storage operations used by the public MCP. More typed endpoint groups will be
added without removing the generic full-API transport.

The public MCP server does **not** expose `request()` to MCP clients. It keeps
its curated, confirmation-gated tool set.

## Planned typed endpoint groups

The PiKVM HTTP API includes authentication, system/logs, HID, ATX, mass
storage, GPIO, streamer/OCR, PiKVM Switch, Redfish, Prometheus metrics, and
raw H.264 video. The core roadmap adds typed wrappers for each group while
preserving version-tolerant access through the generic transport. See the
[PiKVM HTTP API reference](https://docs.pikvm.org/api/).
