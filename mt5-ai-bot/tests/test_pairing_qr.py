"""The private QR format must be safe, simple and interoperable."""
import json

import pytest
from scripts.show_pairing_qr import build_pairing_payload


def test_valid_private_pairing_payload():
    raw = build_pairing_payload(
        "https://wingerapp1.tail8208bf.ts.net",
        "r" * 64, "c" * 64,
    )
    doc = json.loads(raw)
    assert doc["type"] == "emtifize-pair-v1"
    assert doc["url"] == "https://wingerapp1.tail8208bf.ts.net"
    assert doc["read_token"] == "r" * 64
    assert doc["control_token"] == "c" * 64


@pytest.mark.parametrize("url", [
    "http://wingerapp1.tail8208bf.ts.net",
    "https://evil.example.com",
    "https://user@wingerapp1.tail8208bf.ts.net",
    "https://wingerapp1.tail8208bf.ts.net/hijack",
    "https://wingerapp1.tail8208bf.ts.net:8080",
])
def test_insecure_pairing_hosts_are_rejected(url):
    with pytest.raises(ValueError):
        build_pairing_payload(url, "r" * 64, "c" * 64)


def test_control_and_read_secrets_cannot_match():
    with pytest.raises(ValueError):
        build_pairing_payload("https://host.tail.ts.net", "x" * 64, "x" * 64)
