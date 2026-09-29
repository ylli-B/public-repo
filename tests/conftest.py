"""Shared test fixtures.

Tests must never touch the network, a database, or the real .env. Anything that
needs those belongs in a manual probe script, not the suite that gates merges.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


@pytest.fixture(autouse=True)
def _no_ambient_secrets(monkeypatch):
    """Clear notification/provider env so tests never depend on the developer's .env."""
    for key in ("NTFY_TOPIC", "NTFY_SERVER", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
                "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER",
                "TWILIO_MESSAGING_SERVICE_SID", "ALERT_TO_NUMBER", "NOTIFY_CHANNELS",
                "APIFY_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    yield


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Hard-block sockets for the whole suite.

    Not paranoia: an early version of the notification tests patched the wrong
    module and silently delivered a real push notification. A test that can
    reach the internet can also spend money, mutate a live account, or pass only
    because a third party happened to be up.
    """
    import socket

    def _blocked(*a, **k):
        raise AssertionError(
            "test attempted a network connection — mock the client instead"
        )

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


@pytest.fixture
def tmp_state(tmp_path, monkeypatch):
    """Redirect artifact writes into a temp dir."""
    monkeypatch.setenv("EVMAX_STATE_DIR", str(tmp_path))
    return tmp_path
