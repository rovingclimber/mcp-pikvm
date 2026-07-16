from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("pikvm_mcp.audit")


def audit(event: str, details: dict[str, Any], path: Path | None = None) -> None:
    """Emit structured audit events without recording credentials or typed content."""
    record = {"timestamp": datetime.now(UTC).isoformat(), "event": event, **details}
    line = json.dumps(record, sort_keys=True, separators=(",", ":"))
    LOGGER.info(line)
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log:
            log.write(line + "\n")


def content_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
