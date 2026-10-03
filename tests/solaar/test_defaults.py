"""Defaults: the setting values captured the first time plasmaar sees a device, reported as "default"."""

import json

from unittest import mock

import pytest
import yaml

from logitech_receiver.common import NamedInt
from logitech_receiver.common import NamedInts
from logitech_receiver.settings import Kind
from solaar import api
from solaar import configuration

DEV_ID = "B04200000000-BD2BC136"
HAPTIC = NamedInt(0x1A0, "Haptic")
GESTURE = NamedInt(0xC3, "Mouse Gesture Button")
DIVERT = NamedInts(Regular=0, Diverted=1)


def make_setting(name, kind, value=None, choices=None, persist=True):
    setting = mock.Mock(name=name)
    setting.name = name
    setting.label = name.title()
    setting.description = f"{name} description"
    setting.kind = kind
    setting.display = True
    setting.persist = persist
    setting.choices = choices
    setting.range = (1, 50)
    setting.read.return_value = value
    return setting


def make_device(settings, persister=None, online=True):
    device = mock.Mock(name="device")
    device.online = online
    device.modelId, device.unitId = "B04200000000", "BD2BC136"
    device.settings = list(settings)
    device.persister = {} if persister is None else persister
    return device


@pytest.fixture
def registry(monkeypatch):
    listeners = {}
    monkeypatch.setattr(api.listener, "_all_listeners", listeners)

    def add(device):
        device.isDevice = True
        listeners[f"/dev/hidraw{len(listeners)}"] = mock.Mock(receiver=device)
        return device

    return add


def mx_master_settings():
    return [
        make_setting("smart-shift", Kind.RANGE, value=12),
        make_setting("dpi", Kind.CHOICE, value=NamedInt(1000, "1000"), choices=NamedInts.list([800, 1000])),
        make_setting("hires-smooth-invert", Kind.TOGGLE, value=False),
        make_setting("divert-keys", Kind.MAP_CHOICE, value={0x1A0: 1, 0xC3: 2}, choices={HAPTIC: DIVERT, GESTURE: DIVERT}),
        make_setting(
            "reprogrammable-keys", Kind.MAP_CHOICE, value={0x1A0: 0x52, 0xC3: 0xC3}, choices={HAPTIC: DIVERT, GESTURE: DIVERT}
        ),
        make_setting("force-sensing", Kind.RANGE, value={0: 5167}),
        make_setting("haptic-play", Kind.CHOICE, choices=NamedInts(WAVE=9), persist=False),
        make_setting("rgb", Kind.HETERO, value={"ID": 1}),
    ]


def test_capture_records_writable_settings_once():
    device = make_device(mx_master_settings())

    api.capture_defaults(device)

    assert device.persister["_defaults"] == {
        "smart-shift": 12,
        "dpi": 1000,
        "hires-smooth-invert": False,
        "divert-keys": {416: 0, 195: 0},  # factory state, whatever is diverted now
        "reprogrammable-keys": {416: 416, 195: 195},  # factory state, whatever is remapped now
        "force-sensing": {0: 5167},
    }
    assert not isinstance(device.persister["_defaults"]["dpi"], NamedInt)  # plain types: safe to write as YAML
    yaml.safe_dump(device.persister["_defaults"])


def test_capture_never_overwrites_and_fills_what_is_missing():
    settings = mx_master_settings()
    device = make_device(settings, persister={"_defaults": {"smart-shift": 30}})

    api.capture_defaults(device)

    assert device.persister["_defaults"]["smart-shift"] == 30
    assert device.persister["_defaults"]["dpi"] == 1000
    settings[0].read.assert_not_called()


def test_capture_runs_once_per_device_and_process():
    settings = mx_master_settings()
    device = make_device(settings)
    api.capture_defaults(device)
    del device.persister["_defaults"]

    api.capture_defaults(device)

    assert "_defaults" not in device.persister
    assert settings[0].read.call_count == 1


def test_capture_skips_offline_devices_and_retries_later():
    device = make_device(mx_master_settings(), online=False)

    api.capture_defaults(device)
    assert "_defaults" not in device.persister

    device.online = True
    api.capture_defaults(device)
    assert device.persister["_defaults"]["smart-shift"] == 12


def test_capture_skips_unreadable_settings():
    broken = make_setting("dpi", Kind.CHOICE, choices=NamedInts.list([800]))
    broken.read.side_effect = RuntimeError("asleep")
    unknown = make_setting("smart-shift", Kind.RANGE, value=None)
    device = make_device([broken, unknown, make_setting("hires-smooth-invert", Kind.TOGGLE, value=True)])

    api.capture_defaults(device)

    assert device.persister["_defaults"] == {"hires-smooth-invert": True}


def test_captured_maps_are_copies():
    value = {0x1A0: 1}
    device = make_device([make_setting("force-sensing", Kind.MAP_CHOICE, value=value, choices={HAPTIC: DIVERT})])

    api.capture_defaults(device)
    value[0x1A0] = 0  # the setting's own map changes later

    assert device.persister["_defaults"]["force-sensing"] == {416: 1}


def test_capture_without_persister():
    device = make_device(mx_master_settings())
    device.persister = None

    api.capture_defaults(device)  # nothing to store into, nothing raised


def test_capture_schedules_a_configuration_save(monkeypatch):
    save = mock.Mock()
    monkeypatch.setattr(configuration, "save", save)
    device = make_device(mx_master_settings(), persister=configuration._DeviceEntry())

    api.capture_defaults(device)

    save.assert_called_with(defer=True)
    assert device.persister["_defaults"]["smart-shift"] == 12


def test_list_settings_reports_defaults(registry):
    registry(make_device(mx_master_settings()))

    described = {s["name"]: s for s in api.list_settings(DEV_ID)}

    assert described["smart-shift"]["default"] == 12
    assert described["divert-keys"]["default"] == {"416": 0, "195": 0}
    assert described["reprogrammable-keys"]["default"] == {"416": 416, "195": 195}
    assert described["force-sensing"]["default"] == 5167  # presented like its value
    assert "default" not in described["haptic-play"]
    assert "default" not in described["rgb"]
    json.loads(api.to_json(list(described.values())))


def test_list_settings_without_known_defaults(registry):
    registry(make_device(mx_master_settings(), online=False))

    described = api.list_settings(DEV_ID)

    assert all("default" not in s for s in described)


def test_describe_setting_with_defaults():
    setting = make_setting("smart-shift", Kind.RANGE, value=20)

    assert api.describe_setting(setting, defaults={"smart-shift": 12})["default"] == 12
    assert "default" not in api.describe_setting(setting)
