from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class ConfigurationError(ValueError):
    """Raised when a configuration would weaken the local-only boundary."""


def is_local_network_address(address: str) -> bool:
    """Accept only loopback, link-local, RFC1918, or IPv6 unique-local addresses."""
    ip = ipaddress.ip_address(address)
    return bool(ip.is_loopback or ip.is_link_local or ip.is_private)


def validate_pikvm_url(url: str, allow_private_hostnames: bool, allow_insecure_http: bool = False) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ConfigurationError("PIKVM_URL must be an absolute http(s) URL.")
    if parsed.scheme == "http" and not allow_insecure_http:
        raise ConfigurationError("PIKVM_URL must use HTTPS. HTTP needs PIKVM_ALLOW_INSECURE_HTTP=1.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ConfigurationError("PIKVM_URL must not contain credentials, a query, or a fragment.")
    if parsed.path not in {"", "/"}:
        raise ConfigurationError("PIKVM_URL must identify the PiKVM origin only (no path).")

    host = parsed.hostname
    try:
        if not is_local_network_address(host):
            raise ConfigurationError("PIKVM_URL must use a private, link-local, or loopback address.")
    except ValueError:
        if not allow_private_hostnames:
            raise ConfigurationError(
                "PIKVM_URL must use a literal private IP. Set PIKVM_ALLOW_PRIVATE_HOSTNAMES=1 "
                "only for a stable internal DNS name."
            )
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}
        except socket.gaierror as exc:
            raise ConfigurationError("PIKVM_URL hostname could not be resolved.") from exc
        if not addresses or not all(is_local_network_address(address) for address in addresses):
            raise ConfigurationError("PIKVM_URL hostname must resolve exclusively to local-network addresses.")

    # httpx accepts the normalized origin below; reject odd but technically parseable ports.
    try:
        port = parsed.port
    except ValueError as exc:
        raise ConfigurationError("PIKVM_URL contains an invalid port.") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ConfigurationError("PIKVM_URL contains an invalid port.")
    return url.rstrip("/")
