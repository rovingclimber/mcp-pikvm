import pytest

from pikvm_mcp.security import ConfigurationError, is_local_network_address, validate_pikvm_url
from pikvm_mcp.server import _normalised_to_hid


@pytest.mark.parametrize("address", ["127.0.0.1", "192.168.1.20", "10.0.0.1", "172.16.1.1", "fd00::1"])
def test_local_network_addresses_are_accepted(address):
    assert is_local_network_address(address)


@pytest.mark.parametrize("address", ["8.8.8.8", "1.1.1.1", "2001:4860:4860::8888"])
def test_public_addresses_are_rejected(address):
    assert not is_local_network_address(address)


def test_url_requires_literal_ip_by_default():
    with pytest.raises(ConfigurationError, match="literal private IP"):
        validate_pikvm_url("https://pikvm.lan", allow_private_hostnames=False)


def test_url_rejects_public_ip_and_path():
    with pytest.raises(ConfigurationError):
        validate_pikvm_url("https://8.8.8.8", allow_private_hostnames=False)
    with pytest.raises(ConfigurationError, match="no path"):
        validate_pikvm_url("https://192.168.1.20/api/info", allow_private_hostnames=False)


def test_http_requires_explicit_opt_in():
    with pytest.raises(ConfigurationError, match="HTTPS"):
        validate_pikvm_url("http://192.168.1.20", allow_private_hostnames=False)
    assert validate_pikvm_url("http://192.168.1.20", False, allow_insecure_http=True) == "http://192.168.1.20"


def test_normalized_screenshot_coordinates_map_to_center_origin_hid():
    assert _normalised_to_hid(0.0) == -32767
    assert _normalised_to_hid(0.5) == 0
    assert _normalised_to_hid(1.0) == 32767
    with pytest.raises(ValueError):
        _normalised_to_hid(1.01)
