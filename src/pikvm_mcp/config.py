from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .security import ConfigurationError, validate_pikvm_url


def _value(name: str) -> str:
    """Read a value directly or from a Docker/Kubernetes-style *_FILE secret."""
    value = os.getenv(name, "")
    file_name = os.getenv(f"{name}_FILE", "").strip()
    if value and file_name:
        raise ConfigurationError(f"Set only one of {name} or {name}_FILE.")
    if file_name:
        try:
            value = Path(file_name).read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigurationError(f"Unable to read {name}_FILE.") from exc
    return value.strip()


def _required(name: str) -> str:
    value = _value(name)
    if not value:
        raise ConfigurationError(f"{name} is required.")
    return value


def _flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    if raw.strip().lower() in {"1", "true", "yes"}:
        return True
    if raw.strip().lower() in {"0", "false", "no"}:
        return False
    raise ConfigurationError(f"{name} must be true/false.")


@dataclass(frozen=True)
class Settings:
    base_url: str
    username: str
    password: str
    tls_verify: bool | str
    control_secret: str | None
    control_ttl_seconds: int
    screen_capture_enabled: bool
    screenshot_ttl_seconds: int
    audit_log: Path | None

    @classmethod
    def from_environment(cls) -> "Settings":
        allow_private_hostnames = _flag("PIKVM_ALLOW_PRIVATE_HOSTNAMES")
        return cls.from_values(
            url=_required("PIKVM_URL"),
            username=_required("PIKVM_USERNAME"),
            password=_required("PIKVM_PASSWORD"),
            allow_private_hostnames=allow_private_hostnames,
            allow_insecure_http=_flag("PIKVM_ALLOW_INSECURE_HTTP"),
            tls_verify_raw=os.getenv("PIKVM_TLS_VERIFY", "true"),
            allow_insecure_tls=_flag("PIKVM_ALLOW_INSECURE_TLS"),
            ca_bundle=os.getenv("PIKVM_CA_BUNDLE") or None,
            control_secret=_value("PIKVM_MCP_CONTROL_SECRET") or None,
            control_ttl_seconds=os.getenv("PIKVM_MCP_CONTROL_TTL_SECONDS", "300"),
            screen_capture_enabled=_flag("PIKVM_MCP_SCREEN_CAPTURE_ENABLED"),
            screenshot_ttl_seconds=os.getenv("PIKVM_MCP_SCREENSHOT_TTL_SECONDS", "30"),
            audit_log=Path(os.getenv("PIKVM_MCP_AUDIT_LOG", "").strip()) if os.getenv("PIKVM_MCP_AUDIT_LOG", "").strip() else None,
        )

    @classmethod
    def from_values(
        cls,
        *,
        url: str,
        username: str,
        password: str,
        allow_private_hostnames: bool,
        allow_insecure_http: bool = False,
        tls_verify_raw: str = "true",
        allow_insecure_tls: bool = False,
        ca_bundle: str | None = None,
        control_secret: str | None = None,
        control_ttl_seconds: int | str = 300,
        screen_capture_enabled: bool = False,
        screenshot_ttl_seconds: int | str = 30,
        audit_log: Path | None = None,
    ) -> "Settings":
        base_url = validate_pikvm_url(url, allow_private_hostnames, allow_insecure_http)
        if not username.strip() or not password:
            raise ConfigurationError("PiKVM username and password are required.")
        tls_verify_raw = tls_verify_raw.strip().lower()
        if tls_verify_raw in {"true", "1", "yes"}:
            tls_verify: bool | str = ca_bundle or True
        elif tls_verify_raw in {"false", "0", "no"}:
            if not allow_insecure_tls:
                raise ConfigurationError(
                    "Disabling TLS verification requires PIKVM_ALLOW_INSECURE_TLS=1 as a second explicit opt-in."
                )
            tls_verify = False
        else:
            raise ConfigurationError("PIKVM_TLS_VERIFY must be true/false.")

        try:
            ttl = int(control_ttl_seconds)
        except ValueError as exc:
            raise ConfigurationError("PIKVM_MCP_CONTROL_TTL_SECONDS must be an integer.") from exc
        if not 30 <= ttl <= 3600:
            raise ConfigurationError("PIKVM_MCP_CONTROL_TTL_SECONDS must be between 30 and 3600.")
        try:
            screenshot_ttl = int(screenshot_ttl_seconds)
        except ValueError as exc:
            raise ConfigurationError("PIKVM_MCP_SCREENSHOT_TTL_SECONDS must be an integer.") from exc
        if not 5 <= screenshot_ttl <= 300:
            raise ConfigurationError("PIKVM_MCP_SCREENSHOT_TTL_SECONDS must be between 5 and 300.")
        return cls(
            base_url=base_url,
            username=username.strip(),
            password=password,
            tls_verify=tls_verify,
            control_secret=control_secret,
            control_ttl_seconds=ttl,
            screen_capture_enabled=screen_capture_enabled,
            screenshot_ttl_seconds=screenshot_ttl,
            audit_log=audit_log,
        )


@dataclass(frozen=True)
class HttpSettings:
    """Network settings for the Streamable HTTP MCP transport."""

    bearer_token: str
    allowed_hosts: list[str]
    allowed_origins: list[str]

    @classmethod
    def from_environment(cls) -> "HttpSettings":
        token = _required("MCP_HTTP_BEARER_TOKEN")
        if len(token) < 32:
            raise ConfigurationError("MCP_HTTP_BEARER_TOKEN must be at least 32 characters.")
        hosts = _csv("MCP_HTTP_ALLOWED_HOSTS", "localhost:8000,127.0.0.1:8000,[::1]:8000")
        if not hosts:
            raise ConfigurationError("MCP_HTTP_ALLOWED_HOSTS must contain at least one host.")
        origins = _csv("MCP_HTTP_ALLOWED_ORIGINS", "")
        for origin in origins:
            parsed = urlsplit(origin)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"}:
                raise ConfigurationError("MCP_HTTP_ALLOWED_ORIGINS must contain only absolute HTTP(S) origins.")
        return cls(bearer_token=token, allowed_hosts=hosts, allowed_origins=origins)


def _csv(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]
