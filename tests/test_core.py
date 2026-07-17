import pytest

from pikvm_core import PiKVMClient, PiKVMConnection


def test_core_accepts_a_transport_agnostic_connection():
    client = PiKVMClient(PiKVMConnection("https://192.168.1.50", "admin", "password"))

    assert client.connection.base_url == "https://192.168.1.50"


def test_core_rejects_non_api_paths_before_network_access():
    client = PiKVMClient(PiKVMConnection("https://192.168.1.50", "admin", "password"))

    with pytest.raises(ValueError, match="/api/"):
        client.request("GET", "/kvm/")
