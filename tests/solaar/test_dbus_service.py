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
from logitech_receiver.common import NamedInt
from logitech_receiver.common import NamedInts
from logitech_receiver.settings import Kind
from solaar import api
from solaar import buttons
from solaar import dbus_service

# A session-type bus without service directories: a call to a missing name (e.g. kglobalaccel) fails
# instead of activating the desktop's real service on the test bus.
_TEST_BUS_CONFIG = """<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <type>session</type>
  <listen>unix:tmpdir=/tmp</listen>
  <auth>EXTERNAL</auth>
  <policy context="default">
    <allow send_destination="*" eavesdrop="true"/>
    <allow eavesdrop="true"/>
    <allow own="*"/>
  </policy>
</busconfig>
"""


@pytest.fixture
def test_bus(tmp_path):
    """A throwaway dbus-daemon; tests talk to it through private connections only."""
    if shutil.which("dbus-daemon") is None:
        pytest.skip("no dbus-daemon for a private test bus")
    config = tmp_path / "test-bus.conf"
    config.write_text(_TEST_BUS_CONFIG)
    daemon = subprocess.Popen(
        ["dbus-daemon", f"--config-file={config}", "--nofork", "--print-address=1"], stdout=subprocess.PIPE, text=True
    )
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


# --- button actions: ListKdeActions, GetButtonActions, SetButtonAction, ButtonActionsChanged ---

HAPTIC = NamedInt(0x1A0, "Haptic")
GESTURE = NamedInt(0xC3, "Mouse Gesture Button")
MX_MASTER = "B04200000000-BD2BC136"

_KGLOBALACCEL_XML = """
<node>
  <interface name="org.kde.KGlobalAccel">
    <method name="allComponents"><arg type="ao" direction="out"/></method>
  </interface>
  <interface name="org.kde.kglobalaccel.Component">
    <method name="allShortcutInfos"><arg type="a(ssssssaiai)" direction="out"/></method>
    <property name="uniqueName" type="s" access="read"/>
    <property name="friendlyName" type="s" access="read"/>
  </interface>
</node>
"""


@pytest.fixture
def kglobalaccel(test_bus):
    """A fake org.kde.kglobalaccel on the private bus, served from the main loop like the real one."""
    components = {
        "/component/kwin": ("kwin", "KWin", [("Overview", "Basculer vers l'aperçu"), ("Grid View", "Affichage en grille")]),
        "/component/org_kde_spectacle_desktop": (
            "org.kde.spectacle.desktop",
            "Spectacle",
            [("RectangularRegionScreenShot", "Capturer une région rectangulaire")],
        ),
    }
    connection = test_bus.connect_private()
    interfaces = Gio.DBusNodeInfo.new_for_xml(_KGLOBALACCEL_XML).interfaces

    def all_components(_connection, _sender, _path, _interface, _method, _params, invocation):
        invocation.return_value(GLib.Variant("(ao)", (list(components),)))

    def all_shortcut_infos(_connection, _sender, path, _interface, _method, _params, invocation):
        name, label, actions = components[path]
        infos = [(action, text, name, label, "default", "Default Context", [], []) for action, text in actions]
        invocation.return_value(GLib.Variant("(a(ssssssaiai))", (infos,)))

    def get_property(_connection, _sender, path, _interface, prop):
        name, label, _actions = components[path]
        return GLib.Variant("s", name if prop == "uniqueName" else label)

    connection.register_object("/kglobalaccel", interfaces[0], all_components, None, None)
    for path in components:
        connection.register_object(path, interfaces[1], all_shortcut_infos, get_property, None)
    owned = []
    Gio.bus_own_name_on_connection(
        connection, "org.kde.kglobalaccel", Gio.BusNameOwnerFlags.NONE, lambda *_args: owned.append(True), None
    )
    assert _spin(lambda: owned)
    return components


class FakeDivertKeys:
    name = "divert-keys"
    kind = Kind.MAP_CHOICE
    persist = True

    def __init__(self):
        self.choices = {
            HAPTIC: NamedInts(Regular=0, Diverted=1),
            GESTURE: NamedInts(**{"Regular": 0, "Diverted": 1, "Mouse Gestures": 2}),
        }
        self.value = {0x1A0: 0, 0xC3: 0}

    def read(self, cached=True):
        return self.value

    def write_key_value(self, key, value, save=True):
        self.value[int(key)] = value
        return value


@pytest.fixture
def mx_master(monkeypatch):
    """An online MX Master 4 with divertable buttons, known to the (fake) listeners."""
    device = mock.Mock(name="MX Master 4", isDevice=True, online=True, modelId="B04200000000", unitId="BD2BC136")
    device.settings = [FakeDivertKeys()]
    monkeypatch.setattr(api.listener, "_all_listeners", {"/dev/hidraw0": mock.Mock(receiver=device)})
    return device


def _signals(proxy):
    signals = []
    proxy.connect("g-signal", lambda _p, _sender, name, params: signals.append((name, params.unpack())))
    return signals


def _remote_error(proxy, method, signature, *args):
    with pytest.raises(GLib.Error) as error:
        _call(proxy, method, signature, *args)
    return Gio.DBusError.get_remote_error(error.value).rsplit(".", 1)[-1]


def test_list_kde_actions_reads_kglobalaccel(proxy, kglobalaccel):
    (actions_json,) = _call(proxy, "ListKdeActions")

    assert json.loads(actions_json) == [
        {
            "component": "kwin",
            "label": "KWin",
            "actions": [
                {"name": "Grid View", "label": "Affichage en grille"},
                {"name": "Overview", "label": "Basculer vers l'aperçu"},
            ],
        },
        {
            "component": "org.kde.spectacle.desktop",
            "label": "Spectacle",
            "actions": [{"name": "RectangularRegionScreenShot", "label": "Capturer une région rectangulaire"}],
        },
    ]


def test_list_kde_actions_without_kglobalaccel_fails(proxy):
    assert _remote_error(proxy, "ListKdeActions", None) == "Failed"


def test_get_button_actions(proxy, mx_master):
    (buttons_json,) = _call(proxy, "GetButtonActions", "(s)", MX_MASTER)

    result = json.loads(buttons_json)
    assert result["device_id"] == MX_MASTER
    assert [(b["control"], b["name"], b["modes"], b["mode"]) for b in result["buttons"]] == [
        (416, "Haptic", ["off", "press"], "off"),
        (195, "Mouse Gesture Button", ["off", "press", "gesture"], "off"),
    ]


def test_set_button_action_replies_and_signals(proxy, mx_master, isolate_button_actions):
    signals = _signals(proxy)
    config = {"mode": "gesture", "gestures": {"up": {"component": "kwin", "action": "Grid View"}}}

    (button_json,) = _call(proxy, "SetButtonAction", "(sis)", MX_MASTER, 195, json.dumps(config))

    button = json.loads(button_json)
    assert button["mode"] == "gesture"
    assert button["gestures"]["up"] == {"component": "kwin", "action": "Grid View"}
    assert _spin(lambda: len(signals) == 2)
    assert signals == [
        ("SettingChanged", (MX_MASTER, "divert-keys", '{"416": 0, "195": 2}')),
        ("ButtonActionsChanged", (MX_MASTER,)),
    ]
    assert "up: [kwin, Grid View]" in isolate_button_actions.read_text()
    (buttons_json,) = _call(proxy, "GetButtonActions", "(s)", MX_MASTER)
    assert json.loads(buttons_json)["buttons"][1] == button


@pytest.mark.parametrize(
    "device_id, control, config, error",
    [
        (MX_MASTER, 416, '{"mode": "gesture"}', "NotSupported"),
        (MX_MASTER, 999, '{"mode": "press"}', "InvalidValue"),
        (MX_MASTER, 416, '{"press": "Overview"}', "InvalidValue"),
        ("nope", 416, '{"mode": "press"}', "NoSuchDevice"),
    ],
)
def test_set_button_action_errors(proxy, mx_master, device_id, control, config, error):
    assert _remote_error(proxy, "SetButtonAction", "(sis)", device_id, control, config) == error


def test_set_button_action_offline(proxy, mx_master):
    mx_master.online = False

    assert _remote_error(proxy, "SetButtonAction", "(sis)", MX_MASTER, 416, '{"mode": "press"}') == "DeviceOffline"


def test_divert_keys_written_directly_updates_button_actions(proxy, mx_master):
    _call(
        proxy,
        "SetButtonAction",
        "(sis)",
        MX_MASTER,
        416,
        '{"mode": "press", "press": {"component": "kwin", "action": "Overview"}}',
    )
    signals = _signals(proxy)

    _call(proxy, "SetSettingKey", "(ssss)", MX_MASTER, "divert-keys", "416", "0")

    assert _spin(lambda: len(signals) == 2)
    assert [name for name, _args in signals] == ["SettingChanged", "ButtonActionsChanged"]
    assert buttons._mappings[MX_MASTER][416]["mode"] == "off"


def test_button_actions_changed_signal(proxy, service):
    signals = _signals(proxy)

    service.button_actions_changed(MX_MASTER)

    assert _spin(lambda: signals)
    assert signals == [("ButtonActionsChanged", (MX_MASTER,))]


def test_device_added_captures_defaults(proxy, service, monkeypatch):
    device = mock.Mock(online=True)
    device.__bool__ = lambda self: True
    monkeypatch.setattr(api, "device_id", lambda d: MX_MASTER)
    monkeypatch.setattr(api, "describe_device", lambda d: {"id": MX_MASTER})
    capture = mock.Mock()
    monkeypatch.setattr(api, "capture_defaults", capture)
    signals = _signals(proxy)

    service.device_changed(device)

    assert _spin(lambda: signals and capture.called)
    capture.assert_called_once_with(device)
