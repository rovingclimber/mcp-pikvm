"""Transport-agnostic, authenticated PiKVM HTTP API client.

This package deliberately contains no MCP concepts, agent policy, token
handling, or LLM-facing tools. It is reusable by local runtimes and adapters.
"""

from .client import PiKVMClient, PiKVMConnection, PiKVMResponseError

__all__ = ["PiKVMClient", "PiKVMConnection", "PiKVMResponseError"]
