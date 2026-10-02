"""Run the real D-Bus service on a private test bus through private connections.

Never the user's session bus, and never GLib's shared session connection (which exits the
process when its bus goes away)."""

import json
import os
import shutil
import subprocess

from types import SimpleNamespace
from unittest import mock

import pytest

from gi.repository import Gio
from gi.repository import GLib
from solaar import api
from solaar import dbus_service


@pytest.fixture
def test_bus():
    """A throwaway dbus-daemon; tests talk to it through private connections only."""
    if shutil.which("dbus-daemon") is None:
        pytest.skip("no dbus-daemon for a private test bus")
    daemon = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1"], stdout=subprocess.PIPE, text=True)
    address = daemon.stdout.readline().strip()
    connections = []

    def connect():
        connection = Gio.DBusConnection.new_for_address_sync(
            address,
            Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None,
            None,
        )
        connections.append(connection)
        return connection

    yield SimpleNamespace(address=address, connect_private=connect)
    for connection in connections:
        connection.close_sync(None)
    daemon.terminate()
    daemon.wait(timeout=10)


def _spin(condition, timeout=5.0):
    context = GLib.MainContext.default()
    deadline = GLib.get_monotonic_time() + int(timeout * 1_000_000)
    while not condition() and GLib.get_monotonic_time() < deadline:
        context.iteration(False)
    return condition()


@pytest.fixture
def service(test_bus):
    s = dbus_service.Service(connection=test_bus.connect_private())
    s.start()
    assert _spin(lambda: s._registration_id is not None), "service did not register on the bus"
    yield s
    s.stop()


@pytest.fixture
def proxy(service, test_bus):
    return Gio.DBusProxy.new_sync(
        test_bus.connect_private(),
        Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES,
        None,
        dbus_service.BUS_NAME,
        dbus_service.OBJECT_PATH,
        dbus_service.INTERFACE,
        None,
    )


def _call(proxy, method, signature=None, *args):
    """Call asynchronously and spin the default main loop (the service replies from it)."""
    result = {}
    params = GLib.Variant(signature, args) if signature else None

    def done(source, res):
        try:
            result["value"] = source.call_finish(res)
        except GLib.Error as e:
            result["error"] = e

    proxy.call(method, params, Gio.DBusCallFlags.NONE, 5000, None, done)
    assert _spin(lambda: result), f"no reply to {method}"
    if "error" in result:
        raise result["error"]
    return result["value"].unpack() if result["value"] is not None else ()


def test_get_version(proxy):
    assert _call(proxy, "GetVersion") == (str(api.API_VERSION),)


def test_list_devices(proxy, monkeypatch):
    monkeypatch.setattr(api, "list_devices", lambda: [{"id": "B042-1", "name": "MX Master 4"}])

    (devices_json,) = _call(proxy, "ListDevices")

    assert json.loads(devices_json) == [{"id": "B042-1", "name": "MX Master 4"}]


def test_set_setting_replies_and_signals(proxy, monkeypatch):
    setting = mock.Mock()
    setting.name = "dpi"
    monkeypatch.setattr(api, "set_setting", mock.Mock(return_value=(mock.Mock(), setting)))
    monkeypatch.setattr(api, "setting_value", lambda s: 1600)
    signals = []
    proxy.connect("g-signal", lambda _p, _sender, name, params: signals.append((name, params.unpack())))

    (value_json,) = _call(proxy, "SetSetting", "(sss)", "B042-1", "dpi", "1600")

    assert value_json == "1600"
    api.set_setting.assert_called_once_with("B042-1", "dpi", "1600")
    assert _spin(lambda: signals)
    assert signals[0] == ("SettingChanged", ("B042-1", "dpi", "1600"))


def test_api_errors_become_dbus_errors(proxy, monkeypatch):
    monkeypatch.setattr(api, "list_settings", mock.Mock(side_effect=api.NoSuchDevice("no device 'x'")))

    with pytest.raises(GLib.Error) as error:
        _call(proxy, "ListSettings", "(s)", "x")

    assert Gio.DBusError.get_remote_error(error.value) == dbus_service.ERROR_PREFIX + "NoSuchDevice"


def test_unexpected_errors_become_failed(proxy, monkeypatch):
    monkeypatch.setattr(api, "play_haptic", mock.Mock(side_effect=RuntimeError("boom")))

    with pytest.raises(GLib.Error) as error:
        _call(proxy, "PlayHaptic", "(ss)", "B042-1", "WAVE")

    assert Gio.DBusError.get_remote_error(error.value) == dbus_service.ERROR_PREFIX + "Failed"


def test_device_signals(proxy, service, monkeypatch):
    device = mock.Mock()
    device.__bool__ = lambda self: True
    monkeypatch.setattr(api, "device_id", lambda d: "B042-1")
    descriptions = iter([{"id": "B042-1", "online": True}, {"id": "B042-1", "online": False}])
    monkeypatch.setattr(api, "describe_device", lambda d: next(descriptions))
    signals = []
    proxy.connect("g-signal", lambda _p, _sender, name, params: signals.append((name, params.unpack())))

    service.device_changed(device)
    assert _spin(lambda: len(signals) == 1)
    service.device_changed(device)
    assert _spin(lambda: len(signals) == 2)
    device.__bool__ = lambda self: False  # unpaired
    service.device_changed(device)
    assert _spin(lambda: len(signals) == 3)

    assert [name for name, _args in signals] == ["DeviceAdded", "DeviceChanged", "DeviceRemoved"]
    assert json.loads(signals[0][1][0]) == {"id": "B042-1", "online": True}
    assert signals[2][1] == ("B042-1",)


def test_second_service_loses_the_name(service, test_bus):
    lost = mock.Mock()
    second = dbus_service.Service(on_name_lost=lost, connection=test_bus.connect_private())
    second.start()
    try:
        assert _spin(lambda: lost.called)
    finally:
        second.stop()


def test_service_uses_the_given_connection(service, test_bus):
    assert service._connection is not None
    assert service._connection.get_unique_name() is not None
    assert os.environ.get("DBUS_SESSION_BUS_ADDRESS") != test_bus.address  # session bus untouched
