from cryptography.fernet import Fernet

from pikvm_mcp.runtime_config import RuntimeConfig


def test_runtime_config_can_start_unconfigured_then_apply_encrypted_override(monkeypatch, tmp_path):
    monkeypatch.delenv("PIKVM_URL", raising=False)
    monkeypatch.delenv("PIKVM_USERNAME", raising=False)
    monkeypatch.delenv("PIKVM_PASSWORD", raising=False)
    monkeypatch.delenv("PIKVM_PASSWORD_FILE", raising=False)
    monkeypatch.setenv("MCP_CONFIG_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    monkeypatch.setenv("PIKVM_MCP_RUNTIME_CONFIG_PATH", str(tmp_path / "config.enc"))

    runtime = RuntimeConfig()

    assert runtime.status()["message"] == "needs_configuration"
    status, generated_secret = runtime.apply(
        {"url": "https://192.168.1.50", "username": "admin", "password": "secret-password"}
    )

    assert status["configured"] is True
    assert generated_secret
    assert runtime.get().password == "secret-password"
    assert (tmp_path / "config.enc").read_bytes() != b"secret-password"
