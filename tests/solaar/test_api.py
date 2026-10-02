import json

from unittest import mock

import pytest

from logitech_receiver.common import NamedInt
from logitech_receiver.common import NamedInts
from logitech_receiver.settings import Kind
from logitech_receiver.settings_validator import Range
from solaar import api


def make_setting(name, kind, value=None, choices=None, range_=None, write_result="ok"):
    setting = mock.Mock(name=name)
    setting.name = name
    setting.label = name.title()
    setting.description = f"{name} description"
    setting.kind = kind
    setting.display = True
    setting.choices = choices
    setting.range = range_
    setting.read.return_value = value
    setting.write.side_effect = lambda v, save=True: v if write_result == "ok" else None
    setting.write_key_value.side_effect = lambda k, v, save=True: v if write_result == "ok" else None
    return setting


def make_device(settings=(), online=True, model="B04200000000", unit="BD2BC136"):
    device = mock.Mock(name="device")
    device.name = "MX Master 4"
    device.codename = "MX Master 4"
    device.kind = "mouse"
    device.online = online
    device.protocol = 4.5
    device.modelId = model
    device.unitId = unit
    device.serial = ""
    device.number = 255
    device.path = "/dev/hidraw4"
    device.receiver = None
    device.battery_info = mock.Mock(level=45, status=mock.Mock())
    device.battery_info.status.name = "DISCHARGING"
    device.settings = list(settings)
    return device


@pytest.fixture
def registry(monkeypatch):
    """Expose a list of devices through fake listener threads."""
    listeners = {}
    monkeypatch.setattr(api.listener, "_all_listeners", listeners)

    def add(device):
        device.isDevice = True
        listeners[f"/dev/hidraw{len(listeners)}"] = mock.Mock(receiver=device)
        return device

    return add


DPI_CHOICES = NamedInts.list([800, 1000, 1600])
WAVES = NamedInts(SHARP_STATE_CHANGE=0, WAVE=9)
BUTTON = NamedInt(0x1A0, "Haptic")


def test_device_id_prefers_model_and_unit():
    assert api.device_id(make_device()) == "B04200000000-BD2BC136"


def test_device_id_falls_back_to_path_and_number():
    assert api.device_id(make_device(model=None, unit=None)) == "/dev/hidraw4#255"


def test_list_devices(registry):
    registry(make_device())

    [device] = api.list_devices()

    assert device["id"] == "B04200000000-BD2BC136"
    assert device["battery"] == {"level": 45, "status": "DISCHARGING"}
    assert device["online"] is True


def test_devices_walks_receivers(registry, monkeypatch):
    paired = make_device(unit="AAAA")
    receiver = mock.Mock(isDevice=False)
    receiver.__iter__ = lambda self: iter([paired])
    monkeypatch.setattr(api.listener, "_all_listeners", {"/dev/hidraw0": mock.Mock(receiver=receiver)})

    assert list(api.devices()) == [paired]


def test_unknown_device(registry):
    with pytest.raises(api.NoSuchDevice):
        api.list_settings("nope")


def test_describe_settings_by_kind(registry):
    toggle = make_setting("hires-smooth-invert", Kind.TOGGLE, value=False)
    choice = make_setting("dpi", Kind.CHOICE, value=1000, choices=DPI_CHOICES)
    rng = make_setting("smart-shift", Kind.RANGE, value=10, range_=(1, 50))
    keyed = make_setting("divert-keys", Kind.MAP_CHOICE, value={BUTTON: 0}, choices={BUTTON: NamedInts(Regular=0, Diverted=1)})
    hetero = make_setting("rgb", Kind.HETERO, value={"ID": 1})
    registry(make_device([toggle, choice, rng, keyed, hetero]))

    described = {s["name"]: s for s in api.list_settings("B04200000000-BD2BC136")}

    assert described["hires-smooth-invert"]["kind"] == "TOGGLE"
    assert described["dpi"]["choices"][1] == {"value": 1000, "name": "1000"}
    assert (described["smart-shift"]["min"], described["smart-shift"]["max"]) == (1, 50)
    assert described["divert-keys"]["keys"] == [
        {
            "value": 0x1A0,
            "name": "Haptic",
            "choices": [{"value": 0, "name": "Regular"}, {"value": 1, "name": "Diverted"}],
        }
    ]
    assert described["divert-keys"]["value"] == {"416": 0}
    assert described["rgb"]["writable"] is False
    json.loads(api.to_json(list(described.values())))  # everything is JSON-serializable


def test_describe_setting_reports_read_errors(registry):
    broken = make_setting("dpi", Kind.CHOICE, choices=DPI_CHOICES)
    broken.read.side_effect = RuntimeError("device asleep")
    registry(make_device([broken]))

    [described] = api.list_settings("B04200000000-BD2BC136")

    assert described["value"] is None
    assert "device asleep" in described["error"]


@pytest.mark.parametrize(
    "setting, value_json, written",
    [
        (make_setting("invert", Kind.TOGGLE), "true", True),
        (make_setting("dpi", Kind.CHOICE, choices=DPI_CHOICES), "1600", 1600),
        (make_setting("dpi", Kind.CHOICE, choices=DPI_CHOICES), '"800"', 800),
        (make_setting("smart-shift", Kind.RANGE, range_=(1, 50)), "25", 25),
    ],
)
def test_set_setting(registry, setting, value_json, written):
    registry(make_device([setting]))

    api.set_setting("B04200000000-BD2BC136", setting.name, value_json)

    setting.write.assert_called_once_with(written)


@pytest.mark.parametrize(
    "setting, value_json",
    [
        (make_setting("invert", Kind.TOGGLE), "1"),
        (make_setting("dpi", Kind.CHOICE, choices=DPI_CHOICES), "1234"),
        (make_setting("dpi", Kind.CHOICE, choices=DPI_CHOICES), "true"),
        (make_setting("smart-shift", Kind.RANGE, range_=(1, 50)), "51"),
        (make_setting("smart-shift", Kind.RANGE, range_=(1, 50)), "not json"),
    ],
)
def test_set_setting_rejects_invalid_values(registry, setting, value_json):
    registry(make_device([setting]))

    with pytest.raises(api.InvalidValue):
        api.set_setting("B04200000000-BD2BC136", setting.name, value_json)

    setting.write.assert_not_called()


def test_set_setting_unsupported_kind(registry):
    registry(make_device([make_setting("rgb", Kind.HETERO)]))

    with pytest.raises(api.NotSupported):
        api.set_setting("B04200000000-BD2BC136", "rgb", "{}")


def test_set_setting_unknown_setting(registry):
    registry(make_device([]))

    with pytest.raises(api.NoSuchSetting):
        api.set_setting("B04200000000-BD2BC136", "dpi", "800")


def test_set_setting_offline_device(registry):
    setting = make_setting("dpi", Kind.CHOICE, choices=DPI_CHOICES)
    registry(make_device([setting], online=False))

    with pytest.raises(api.DeviceOffline):
        api.set_setting("B04200000000-BD2BC136", "dpi", "800")


def test_set_setting_write_failure(registry):
    setting = make_setting("dpi", Kind.CHOICE, choices=DPI_CHOICES, write_result=None)
    registry(make_device([setting]))

    with pytest.raises(api.ApiError):
        api.set_setting("B04200000000-BD2BC136", "dpi", "800")


def test_set_setting_key(registry):
    keyed = make_setting("divert-keys", Kind.MAP_CHOICE, choices={BUTTON: NamedInts(Regular=0, Diverted=1)})
    registry(make_device([keyed]))

    api.set_setting_key("B04200000000-BD2BC136", "divert-keys", "416", "1")

    keyed.write_key_value.assert_called_once_with(0x1A0, 1)


def test_set_setting_key_range_space(registry):
    keyed = make_setting("eq", Kind.MAP_CHOICE, choices={NamedInt(0, "Band 1"): Range(min=-12, max=12)})
    registry(make_device([keyed]))

    api.set_setting_key("B04200000000-BD2BC136", "eq", "0", "-3")

    keyed.write_key_value.assert_called_once_with(0, -3)


@pytest.mark.parametrize("key_json, value_json", [("999", "1"), ("416", "7"), ('"abc"', "1")])
def test_set_setting_key_rejects_invalid(registry, key_json, value_json):
    keyed = make_setting("divert-keys", Kind.MAP_CHOICE, choices={BUTTON: NamedInts(Regular=0, Diverted=1)})
    registry(make_device([keyed]))

    with pytest.raises(api.InvalidValue):
        api.set_setting_key("B04200000000-BD2BC136", "divert-keys", key_json, value_json)


def test_play_haptic_by_name(registry):
    play = make_setting("haptic-play", Kind.CHOICE, choices=WAVES)
    registry(make_device([play]))

    api.play_haptic("B04200000000-BD2BC136", "WAVE")

    play.write.assert_called_once_with(9, save=False)


def test_play_haptic_unsupported(registry):
    registry(make_device([]))

    with pytest.raises(api.NotSupported):
        api.play_haptic("B04200000000-BD2BC136", "WAVE")


def test_single_key_map_value_is_presented_as_scalar(registry):
    force = make_setting("force-sensing", Kind.RANGE, value={0: 5167}, range_=(4134, 6872))
    registry(make_device([force]))

    [described] = api.list_settings("B04200000000-BD2BC136")

    assert described["value"] == 5167
    assert api.setting_value(force) == 5167
