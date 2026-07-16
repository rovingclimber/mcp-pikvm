from pikvm_mcp.config import pikvm_is_configured


def test_pikvm_is_not_configured_without_all_connection_values(monkeypatch):
    monkeypatch.delenv("PIKVM_URL", raising=False)
    monkeypatch.delenv("PIKVM_USERNAME", raising=False)
    monkeypatch.delenv("PIKVM_PASSWORD", raising=False)
    assert not pikvm_is_configured()


def test_pikvm_is_configured_only_with_all_connection_values(monkeypatch):
    monkeypatch.setenv("PIKVM_URL", "https://192.168.1.50")
    monkeypatch.setenv("PIKVM_USERNAME", "admin")
    monkeypatch.setenv("PIKVM_PASSWORD", "password")
    assert pikvm_is_configured()
