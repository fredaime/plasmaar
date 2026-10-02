from unittest import mock

import pytest

from gi.repository import GLib
from logitech_receiver import desktop_notifications

# The mock_notification_bus autouse fixture (tests/conftest.py) replaces the
# D-Bus proxy, so these exercise the real code paths without raising real
# desktop notifications.


class MockDevice(mock.Mock):
    name = "MockDevice"
    kind = "mouse"


def _notify_args(proxy, call=-1):
    method, params, *_ = proxy.call_sync.call_args_list[call].args
    assert method == "Notify"
    assert params.get_type_string() == "(susssasa{sv}i)"
    return params.unpack()


def test_init_with_connected_proxy():
    assert desktop_notifications.init() is True


def test_init_without_session_bus(monkeypatch):
    monkeypatch.setattr(desktop_notifications, "_proxy", None)
    monkeypatch.setattr(
        desktop_notifications.Gio.DBusProxy, "new_for_bus_sync", mock.Mock(side_effect=GLib.Error("no session bus"))
    )

    assert desktop_notifications.init() is False
    assert desktop_notifications.show(MockDevice(), "connected") is None


def test_uninit_drops_proxy_and_ids(monkeypatch):
    desktop_notifications._notifications["MockDevice"] = 3

    assert desktop_notifications.uninit() is None
    assert desktop_notifications._proxy is None
    assert desktop_notifications._notifications == {}


def test_show_sends_notify(mock_notification_bus):
    result = desktop_notifications.show(MockDevice(), "connected")

    assert result == 7
    app, replaces, icon, summary, body, actions, hints, timeout = _notify_args(mock_notification_bus)
    assert (app, replaces, icon, summary, body, actions, timeout) == (
        "plasmaar",
        0,
        "input-mouse",
        "MockDevice",
        "connected",
        [],
        -1,
    )
    assert hints == {"desktop-entry": "plasmaar", "urgency": 1}


def test_show_replaces_previous_notification_of_device(mock_notification_bus):
    desktop_notifications.show(MockDevice(), "connected")
    desktop_notifications.show(MockDevice(), "disconnected")

    assert _notify_args(mock_notification_bus, 0)[1] == 0
    assert _notify_args(mock_notification_bus, 1)[1] == 7


def test_show_explicit_icon(mock_notification_bus):
    desktop_notifications.show(MockDevice(), "low battery", icon="battery-caution")

    assert _notify_args(mock_notification_bus)[2] == "battery-caution"


def test_show_service_error_returns_none(mock_notification_bus):
    mock_notification_bus.call_sync.side_effect = GLib.Error("service unavailable")

    assert desktop_notifications.show(MockDevice(), "connected") is None


@pytest.mark.parametrize(
    "kind, expected",
    [
        (None, "preferences-desktop-peripherals"),
        ("mouse", "input-mouse"),
        ("headset", "input-headset"),
    ],
)
def test_device_icon_name(kind, expected):
    assert desktop_notifications.device_icon_name(f"icon-test-{kind}", kind) == expected
