"""No broker, GUI or credentials are touched in QR protocol tests."""
import json

import pytest

from scripts.show_pairing_qr import payload_from_env


def test_qr_contains_exact_private_host_and_distinct_tokens(monkeypatch):
    monkeypatch.setenv("EMTIFIZE_PAIR_URL", "https://wingerapp1.tail8208bf.ts.net")
    monkeypatch.setenv("BOT_STATUS_READ_TOKEN", "a" * 50)
    monkeypatch.setenv("BOT_DEMO_CONTROL_TOKEN", "b" * 50)
    payload = json.loads(payload_from_env())
    assert payload == {
        "type": "emtifize-pair-v1",
        "url": "https://wingerapp1.tail8208bf.ts.net",
        "read_token": "a" * 50,
        "control_token": "b" * 50,
    }


@pytest.mark.parametrize("url", [
    "http://wingerapp1.tail8208bf.ts.net",
    "https://untrusted.example",
    "https://evil.ts.net.evil.example",
    "https://person@wingerapp1.tail8208bf.ts.net",
    "https://wingerapp1.tail8208bf.ts.net/other",
])
def test_qr_rejects_insecure_or_unexpected_urls(monkeypatch, url):
    monkeypatch.setenv("EMTIFIZE_PAIR_URL", url)
    monkeypatch.setenv("BOT_STATUS_READ_TOKEN", "a" * 50)
    monkeypatch.setenv("BOT_DEMO_CONTROL_TOKEN", "b" * 50)
    with pytest.raises(ValueError):
        payload_from_env()


def test_qr_rejects_duplicate_control_and_read_secrets(monkeypatch):
    monkeypatch.setenv("EMTIFIZE_PAIR_URL", "https://wingerapp1.tail8208bf.ts.net")
    monkeypatch.setenv("BOT_STATUS_READ_TOKEN", "a" * 50)
    monkeypatch.setenv("BOT_DEMO_CONTROL_TOKEN", "a" * 50)
    with pytest.raises(ValueError):
        payload_from_env()
