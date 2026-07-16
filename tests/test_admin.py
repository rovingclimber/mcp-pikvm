from cryptography.fernet import Fernet
from starlette.testclient import TestClient

from pikvm_mcp.admin import create_admin_app
from pikvm_mcp.runtime_config import RuntimeConfig


def test_admin_status_requires_its_own_bearer_token(monkeypatch, tmp_path):
    admin_token = "a" * 32
    monkeypatch.delenv("PIKVM_URL", raising=False)
    monkeypatch.delenv("PIKVM_USERNAME", raising=False)
    monkeypatch.delenv("PIKVM_PASSWORD", raising=False)
    monkeypatch.delenv("PIKVM_PASSWORD_FILE", raising=False)
    monkeypatch.setenv("MCP_ADMIN_TOKEN", admin_token)
    monkeypatch.setenv("MCP_CONFIG_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    monkeypatch.setenv("PIKVM_MCP_RUNTIME_CONFIG_PATH", str(tmp_path / "config.enc"))
    client = TestClient(create_admin_app(RuntimeConfig()))

    assert client.get("/api/status").status_code == 401
    response = client.get("/api/status", headers={"Authorization": f"Bearer {admin_token}"})

    assert response.status_code == 200
    assert response.json()["message"] == "needs_configuration"
