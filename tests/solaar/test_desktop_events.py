"""Desktop event sources and the desktop-integration D-Bus methods, on a private test bus.

Everything talks to a throwaway dbus-daemon through private connections: never the user's
session bus, and never GLib's shared session connection. Notify calls are made with
NO_AUTO_START so the test bus never activates a real notification server."""

import json
import os
import shutil
import subprocess
import threading

from types import SimpleNamespace
from unittest import mock

import pytest

from gi.repository import Gio
from gi.repository import GLib
from logitech_receiver import diversion
from solaar import api
from solaar import dbus_service
from solaar import desktop_events
from solaar import haptic_events

FLAGS = Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION

NOTIFICATIONS_XML = """
<node>
  <interface name="org.freedesktop.Notifications">
    <method name="Notify">
      <arg type="s" direction="in"/><arg type="u" direction="in"/><arg type="s" direction="in"/>
      <arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="as" direction="in"/>
      <arg type="a{sv}" direction="in"/><arg type="i" direction="in"/>
      <arg type="u" direction="out"/>
    </method>
    <property name="Inhibited" type="b" access="read"/>
  </interface>
</node>
"""


@pytest.fixture
def bus():
    """A throwaway dbus-daemon, reached through private connections only."""
    if shutil.which("dbus-daemon") is None:
        pytest.skip("no dbus-daemon for a private test bus")
    daemon = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1"], stdout=subprocess.PIPE, text=True)
    address = daemon.stdout.readline().strip()
    connections = []

    def connect():
        connection = Gio.DBusConnection.new_for_address_sync(address, FLAGS, None, None)
        connections.append(connection)
        return connection

    yield SimpleNamespace(address=address, connect=connect)
    for connection in connections:
        if not connection.is_closed():
            connection.close_sync(None)
    daemon.terminate()
    daemon.wait(timeout=10)


def _spin(condition, timeout=5.0):
    context = GLib.MainContext.default()
    deadline = GLib.get_monotonic_time() + int(timeout * 1_000_000)
    while not condition() and GLib.get_monotonic_time() < deadline:
        context.iteration(False)
    return condition()


def _settle(seconds=0.3):
    _spin(lambda: False, seconds)


def _own_name(connection, name):
    (reply,) = connection.call_sync(
        "org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus",
        "RequestName",
        GLib.Variant("(su)", (name, 0)),
        GLib.VariantType("(u)"),
        Gio.DBusCallFlags.NONE,
        5000,
        None,
    ).unpack()
    assert reply == 1, f"could not own {name}"


@pytest.fixture
def events(bus):
    """DesktopEvents on the test bus, with its events collected."""
    received = []
    sources = desktop_events.DesktopEvents(received.append, connection=bus.connect(), address=bus.address)
    sources.start()
    assert _spin(lambda: sources.monitoring), "did not become a monitor"
    yield SimpleNamespace(sources=sources, received=received)
    sources.stop()


def _notify(connection, app_name="org.kde.konversation", replaces_id=0, hints=None):
    hints = {key: GLib.Variant(*value) for key, value in (hints or {}).items()}
    connection.call(
        desktop_events.NOTIFICATIONS_BUS_NAME,
        desktop_events.NOTIFICATIONS_PATH,
        desktop_events.NOTIFICATIONS_INTERFACE,
        "Notify",
        GLib.Variant("(susssasa{sv}i)", (app_name, replaces_id, "", "summary", "body", [], hints, -1)),
        None,
        Gio.DBusCallFlags.NO_AUTO_START,
        2000,
        None,
        None,
    )


def _notification_server(bus, inhibited):
    """A fake notification server owning org.freedesktop.Notifications; inhibited is a 1-item list."""
    connection = bus.connect()
    node = Gio.DBusNodeInfo.new_for_xml(NOTIFICATIONS_XML)

    def method_call(_connection, _sender, _path, _interface, _method, _parameters, invocation):
        invocation.return_value(GLib.Variant("(u)", (1,)))

    def get_property(_connection, _sender, _path, _interface, _name):
        return GLib.Variant("b", inhibited[0])

    connection.register_object(desktop_events.NOTIFICATIONS_PATH, node.interfaces[0], method_call, get_property, None)
    _own_name(connection, desktop_events.NOTIFICATIONS_BUS_NAME)
    return connection


# --- virtual desktops ---


def _switch_desktop(kwin):
    kwin.emit_signal(
        None,
        desktop_events.VIRTUAL_DESKTOPS_PATH,
        desktop_events.VIRTUAL_DESKTOPS_INTERFACE,
        "currentChanged",
        GLib.Variant("(s)", ("403442f4-f7c7-46bf-a018-e4cf33cee2c3",)),
    )


def test_desktop_switch(bus, events):
    kwin = bus.connect()
    _own_name(kwin, desktop_events.KWIN_BUS_NAME)

    _switch_desktop(kwin)

    assert _spin(lambda: events.received == ["desktop_switch"])


def test_desktop_switch_only_from_kwin(bus, events):
    impostor = bus.connect()

    _switch_desktop(impostor)
    _settle()

    assert events.received == []


def test_stop_unsubscribes(bus, events):
    kwin = bus.connect()
    _own_name(kwin, desktop_events.KWIN_BUS_NAME)
    events.sources.stop()

    _switch_desktop(kwin)
    _settle()

    assert events.received == []
    assert events.sources._monitor is None


# --- notifications ---


def test_notification_without_notification_server(bus, events):
    """No server, so no Inhibited property to read: the notification still counts."""
    _notify(bus.connect())

    assert _spin(lambda: events.received == ["notification"])


@pytest.mark.parametrize("inhibited, expected", [(False, ["notification"]), (True, [])])
def test_notification_respects_do_not_disturb(bus, events, inhibited, expected):
    _notification_server(bus, [inhibited])

    _notify(bus.connect())
    _settle(0.5)

    assert events.received == expected


def test_own_and_updated_notifications_are_ignored(bus, events):
    app = bus.connect()
    _notify(app, app_name="plasmaar")
    _notify(app, app_name="python3", hints={"desktop-entry": ("s", "io.github.fredaime.plasmaar")})
    _notify(app, replaces_id=42)
    _notify(app, hints={"urgency": ("y", 0)})
    _notify(app, app_name="Firefox", hints={"urgency": ("y", 2)})  # the only one that counts

    assert _spin(lambda: events.received)
    _settle()
    assert events.received == ["notification"]


def test_monitor_does_not_answer_monitored_calls(bus, events):
    """A monitor that sends anything is disconnected by the bus; the monitored calls are swallowed."""
    _notify(bus.connect())
    assert _spin(lambda: events.received)
    _settle()

    assert events.sources._monitor is not None
    assert not events.sources._monitor.is_closed()


@pytest.mark.parametrize(
    "app_name, replaces_id, hints, wanted",
    [
        ("Firefox", 0, {}, True),
        ("Firefox", 0, {"urgency": 1}, True),
        ("Firefox", 0, {"urgency": 2}, True),
        ("Firefox", 0, {"urgency": 0}, False),
        ("Firefox", 3, {}, False),
        ("plasmaar", 0, {}, False),
        ("", 0, {"desktop-entry": "io.github.fredaime.plasmaar"}, False),
        ("", 0, {"desktop-entry": "org.kde.kmail2"}, True),
        ("Firefox", 0, None, True),
    ],
)
def test_wanted_notification(app_name, replaces_id, hints, wanted):
    assert desktop_events.wanted_notification(app_name, replaces_id, hints) is wanted


def test_refused_monitor_is_logged(caplog):
    sources = desktop_events.DesktopEvents(mock.Mock())
    monitor = mock.Mock()
    monitor.call_finish.side_effect = GLib.Error("Access denied", "g-dbus-error-quark", 9)
    sources._monitor = monitor

    sources._became_monitor(monitor, None)

    assert "cannot watch notifications" in caplog.text
    monitor.close_sync.assert_called_once()
    assert sources._monitor is None and not sources.monitoring


def test_unreachable_bus_is_logged(caplog):
    sources = desktop_events.DesktopEvents(mock.Mock(), connection=mock.Mock(), address="unix:path=/nonexistent/plasmaar-test")
    sources.start()
    try:
        assert _spin(lambda: "cannot connect to the session bus" in caplog.text)
    finally:
        sources.stop()


# --- the D-Bus methods (GetHapticEvents, SetHapticEvent, SetActiveWindow) ---


@pytest.fixture
def proxy(bus):
    service = dbus_service.Service(connection=bus.connect())
    service.start()
    assert _spin(lambda: service._registration_id is not None), "service did not register on the bus"
    yield SimpleNamespace(
        proxy=Gio.DBusProxy.new_sync(
            bus.connect(),
            Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES,
            None,
            dbus_service.BUS_NAME,
            dbus_service.OBJECT_PATH,
            dbus_service.INTERFACE,
            None,
        ),
        service=service,
    )
    service.stop()


def _call(proxy, method, signature=None, *args):
    result = {}

    def done(source, res):
        try:
            result["value"] = source.call_finish(res)
        except GLib.Error as e:
            result["error"] = e

    proxy.call(method, GLib.Variant(signature, args) if signature else None, Gio.DBusCallFlags.NONE, 5000, None, done)
    assert _spin(lambda: result), f"no reply to {method}"
    if "error" in result:
        raise result["error"]
    return result["value"].unpack() if result["value"] is not None else ()


DESCRIPTION = {
    "device_id": "B042-1",
    "waveforms": ["SHARP STATE CHANGE", "WAVE"],
    "events": [
        {"event": "notification", "label": "New notification", "waveform": "WAVE"},
        {"event": "desktop_switch", "label": "Virtual desktop switched", "waveform": None},
        {"event": "battery_low", "label": "Battery low", "waveform": None},
    ],
}


def test_get_haptic_events(proxy, monkeypatch):
    get = mock.Mock(return_value=DESCRIPTION)
    monkeypatch.setattr(haptic_events, "get_haptic_events", get)

    (result,) = _call(proxy.proxy, "GetHapticEvents", "(s)", "B042-1")

    assert json.loads(result) == DESCRIPTION
    get.assert_called_once_with("B042-1")


def test_set_haptic_event(proxy, monkeypatch):
    set_event = mock.Mock(return_value=DESCRIPTION)
    monkeypatch.setattr(haptic_events, "set_haptic_event", set_event)

    (result,) = _call(proxy.proxy, "SetHapticEvent", "(sss)", "B042-1", "notification", "WAVE")

    assert json.loads(result) == DESCRIPTION
    set_event.assert_called_once_with("B042-1", "notification", "WAVE")


@pytest.mark.parametrize(
    "error, name",
    [
        (api.NoSuchDevice("x"), "NoSuchDevice"),
        (api.NotSupported("x"), "NotSupported"),
        (api.InvalidValue("x"), "InvalidValue"),
    ],
)
def test_haptic_event_errors(proxy, monkeypatch, error, name):
    monkeypatch.setattr(haptic_events, "set_haptic_event", mock.Mock(side_effect=error))

    with pytest.raises(GLib.Error) as raised:
        _call(proxy.proxy, "SetHapticEvent", "(sss)", "B042-1", "lid_closed", "WAVE")

    assert Gio.DBusError.get_remote_error(raised.value) == dbus_service.ERROR_PREFIX + name


def test_haptic_events_end_to_end_through_the_persister(proxy, monkeypatch):
    """The real haptic_events functions behind the D-Bus methods, with a fake device."""
    from logitech_receiver.common import NamedInts
    from solaar import configuration

    monkeypatch.setattr(configuration, "save", mock.Mock())
    setting = mock.Mock(choices=NamedInts(SHARP_STATE_CHANGE=0, WAVE=9))
    setting.name = "haptic-play"
    device = SimpleNamespace(online=True, settings=[setting], persister=configuration._DeviceEntry())
    monkeypatch.setattr(api, "find_device", lambda dev_id: device)
    monkeypatch.setattr(api, "device_id", lambda d: "B042-1")

    (result,) = _call(proxy.proxy, "SetHapticEvent", "(sss)", "B042-1", "notification", "WAVE")
    assert json.loads(result) == DESCRIPTION
    assert device.persister["_haptic_events"] == {"notification": "WAVE"}

    (result,) = _call(proxy.proxy, "GetHapticEvents", "(s)", "B042-1")
    assert json.loads(result) == DESCRIPTION


@pytest.fixture
def kwin_focus(monkeypatch):
    monkeypatch.setattr(diversion, "_kwin_focus", None)


def test_set_active_window(proxy, kwin_focus):
    assert _call(proxy.proxy, "SetActiveWindow", "(ssi)", "org.mozilla.firefox", "firefox", os.getpid()) == ()

    resource_class, resource_name, process_name = diversion.kwin_focus_prog()
    assert (resource_class, resource_name) == ("org.mozilla.firefox", "firefox")
    assert process_name and process_name in open(f"/proc/{os.getpid()}/comm").read()


def test_set_active_window_none(proxy, kwin_focus):
    _call(proxy.proxy, "SetActiveWindow", "(ssi)", "", "", 0)

    assert diversion.kwin_focus_prog() == ()


def test_set_active_window_does_not_wait_for_the_worker(proxy, kwin_focus):
    """Focus changes must not queue behind a device call that waits for a sleeping device."""
    release = threading.Event()
    proxy.service._worker(release.wait, 10)
    try:
        _call(proxy.proxy, "SetActiveWindow", "(ssi)", "konsole", "konsole", 0)
        assert diversion.kwin_focus_prog() == ("konsole", "konsole", "")
    finally:
        release.set()


def test_set_active_window_failure_is_an_error(proxy, monkeypatch):
    monkeypatch.setattr(diversion, "set_kwin_focus", mock.Mock(side_effect=RuntimeError("boom")))

    with pytest.raises(GLib.Error) as raised:
        _call(proxy.proxy, "SetActiveWindow", "(ssi)", "konsole", "konsole", 1)

    assert Gio.DBusError.get_remote_error(raised.value) == dbus_service.ERROR_PREFIX + "Failed"


def test_set_active_window_rejects_wrong_types(proxy, kwin_focus):
    """The KWin script must send an int32 pid; GDBus checks the signature before our handler runs."""
    with pytest.raises(GLib.Error):
        _call(proxy.proxy, "SetActiveWindow", "(ssd)", "konsole", "konsole", 1.0)

    assert diversion.kwin_focus_prog() is None
