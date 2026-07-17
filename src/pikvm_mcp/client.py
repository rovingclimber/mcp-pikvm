"""Compatibility import for the PiKVM MCP façade.

New integrations should import :class:`pikvm_core.PiKVMClient` directly.
"""

from pikvm_core import PiKVMClient

__all__ = ["PiKVMClient"]
