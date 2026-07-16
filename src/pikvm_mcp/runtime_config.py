from __future__ import annotations

import json
import os
import secrets
import threading
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from .config import Settings, _value
from .security import ConfigurationError


class RuntimeConfig:
    """Keep a validated PiKVM configuration, optionally persisted encrypted at rest."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._path = Path(os.getenv("PIKVM_MCP_RUNTIME_CONFIG_PATH", "/var/lib/pikvm-mcp/config.json.enc"))
        key = _value("MCP_CONFIG_ENCRYPTION_KEY")
        self._fernet = Fernet(key.encode("ascii")) if key else None
        self._settings: Settings | None = None
        self._source = "unconfigured"
        self._revision = 0
        self._load()

    def _bootstrap(self) -> Settings | None:
        required = ("PIKVM_URL", "PIKVM_USERNAME")
        if not all(os.getenv(name, "").strip() for name in required) or not _value("PIKVM_PASSWORD"):
            return None
        return Settings.from_environment()

    def _load(self) -> None:
        bootstrap = self._bootstrap()
        if self._path.exists():
            if not self._fernet:
                raise ConfigurationError("MCP_CONFIG_ENCRYPTION_KEY is required to read runtime configuration.")
            try:
                payload = json.loads(self._fernet.decrypt(self._path.read_bytes()).decode("utf-8"))
            except (OSError, InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ConfigurationError("The encrypted runtime configuration cannot be read.") from exc
            self._settings = self._settings_from_payload(payload, bootstrap)
            self._source = "runtime_override"
        elif bootstrap:
            self._settings = bootstrap
            self._source = "bootstrap"
        if self._settings:
            self._revision = 1

    @staticmethod
    def _settings_from_payload(payload: dict[str, Any], fallback: Settings | None) -> Settings:
        try:
            url = str(payload["url"])
            username = str(payload["username"])
            password = str(payload["password"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigurationError("Runtime configuration is incomplete.") from exc
        return Settings.from_values(
            url=url,
            username=username,
            password=password,
            allow_private_hostnames=True,
            control_secret=str(payload.get("control_secret") or (fallback.control_secret if fallback else "")) or None,
            control_ttl_seconds=int(payload.get("control_ttl_seconds", fallback.control_ttl_seconds if fallback else 300)),
            screen_capture_enabled=bool(payload.get("screen_capture_enabled", fallback.screen_capture_enabled if fallback else False)),
            screenshot_ttl_seconds=int(payload.get("screenshot_ttl_seconds", fallback.screenshot_ttl_seconds if fallback else 30)),
            audit_log=fallback.audit_log if fallback else None,
        )

    def get(self) -> Settings:
        with self._lock:
            if not self._settings:
                raise ConfigurationError("PiKVM is not configured. Open the local admin UI to add its URL and credentials.")
            return self._settings

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "configured": self._settings is not None,
                "source": self._source,
                "message": "ready" if self._settings else "needs_configuration",
            }

    def revision(self) -> int:
        with self._lock:
            return self._revision

    def apply(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        """Validate, persist, and atomically activate a config. Never return stored credentials."""
        with self._lock:
            current = self._settings
            password = str(payload.get("password") or "") or (current.password if current else "")
            control_secret = str(payload.get("control_secret") or "") or (current.control_secret if current else "")
            generated_secret: str | None = None
            if not control_secret:
                generated_secret = secrets.token_urlsafe(32)
                control_secret = generated_secret
            prepared = {
                "url": str(payload.get("url") or ""),
                "username": str(payload.get("username") or ""),
                "password": password,
                "control_secret": control_secret,
                "control_ttl_seconds": int(payload.get("control_ttl_seconds", current.control_ttl_seconds if current else 300)),
                "screen_capture_enabled": bool(payload.get("screen_capture_enabled", current.screen_capture_enabled if current else False)),
                "screenshot_ttl_seconds": int(payload.get("screenshot_ttl_seconds", current.screenshot_ttl_seconds if current else 30)),
            }
            settings = self._settings_from_payload(prepared, current)
            if not self._fernet:
                raise ConfigurationError("MCP_CONFIG_ENCRYPTION_KEY is required for live configuration changes.")
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_suffix(".tmp")
            temporary.write_bytes(self._fernet.encrypt(json.dumps(prepared, separators=(",", ":")).encode("utf-8")))
            os.replace(temporary, self._path)
            self._settings = settings
            self._source = "runtime_override"
            self._revision += 1
            return self.status(), generated_secret
