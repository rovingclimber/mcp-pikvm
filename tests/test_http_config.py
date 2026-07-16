import pytest

from pikvm_mcp.config import HttpSettings
from pikvm_mcp.security import ConfigurationError


def test_http_settings_accepts_file_backed_bearer_token(monkeypatch, tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("a" * 32, encoding="utf-8")
    monkeypatch.setenv("MCP_HTTP_BEARER_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("MCP_HTTP_ALLOWED_HOSTS", "mcp.example.test")
    monkeypatch.setenv("MCP_HTTP_ALLOWED_ORIGINS", "https://console.example.test")

    settings = HttpSettings.from_environment()

    assert settings.bearer_token == "a" * 32
    assert settings.allowed_hosts == ["mcp.example.test"]
    assert settings.allowed_origins == ["https://console.example.test"]
    assert settings.allowed_client_networks == []


def test_http_settings_rejects_short_bearer_token(monkeypatch):
    monkeypatch.setenv("MCP_HTTP_BEARER_TOKEN", "short")
    with pytest.raises(ConfigurationError, match="at least 32"):
        HttpSettings.from_environment()


def test_http_settings_accepts_client_networks(monkeypatch):
    monkeypatch.setenv("MCP_HTTP_BEARER_TOKEN", "a" * 32)
    monkeypatch.setenv("MCP_HTTP_ALLOWED_CLIENT_NETWORKS", "192.168.0.0/24,10.0.0.0/8")

    settings = HttpSettings.from_environment()

    assert str(settings.allowed_client_networks[0]) == "192.168.0.0/24"
