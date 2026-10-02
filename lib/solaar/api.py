## Copyright (C) 2026  plasmaar contributors
##
## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License along
## with this program; if not, write to the Free Software Foundation, Inc.,
## 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

"""Front-end API over the device core: device and setting descriptions as JSON-ready data.

Independent of D-Bus so it can be tested and reused; solaar.dbus_service exposes it on the
session bus. Functions here may talk to devices and must run off the main loop.
"""

from __future__ import annotations

import json

from logitech_receiver.common import NamedInt
from logitech_receiver.settings import Kind
from logitech_receiver.settings_validator import Range

from solaar import listener

API_VERSION = 1

# setting kinds that can be written through the API; others are listed read-only
WRITABLE_KINDS = (Kind.TOGGLE, Kind.CHOICE, Kind.RANGE, Kind.MAP_CHOICE)


class ApiError(Exception):
    dbus_name = "Failed"


class NoSuchDevice(ApiError):
    dbus_name = "NoSuchDevice"


class NoSuchSetting(ApiError):
    dbus_name = "NoSuchSetting"


class InvalidValue(ApiError):
    dbus_name = "InvalidValue"


class NotSupported(ApiError):
    dbus_name = "NotSupported"


class DeviceOffline(ApiError):
    dbus_name = "DeviceOffline"


# --- JSON ---


def _json_default(value):
    if isinstance(value, (set, tuple)):
        return list(value)
    if hasattr(value, "__int__"):
        return int(value)
    return str(value)


def _json_keys(value):
    """JSON object keys must be strings: turn int/NamedInt keys into their decimal string."""
    if isinstance(value, dict):
        return {str(int(k)) if isinstance(k, int) else str(k): _json_keys(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_keys(v) for v in value]
    if isinstance(value, NamedInt):
        return int(value)
    return value


def to_json(value) -> str:
    return json.dumps(_json_keys(value), default=_json_default)


def from_json(text: str):
    try:
        return json.loads(text)
    except (TypeError, ValueError) as e:
        raise InvalidValue(f"not valid JSON: {text!r}") from e


# --- devices ---


def device_id(device) -> str:
    """A stable id: model and unit id when the device reports them, else its connection path and number."""
    model, unit = getattr(device, "modelId", None), getattr(device, "unitId", None)
    if model and unit:
        return f"{model}-{unit}"
    path = device.receiver.path if getattr(device, "receiver", None) else device.path
    return f"{path}#{device.number}"


def devices():
    """All devices currently known to the listeners (directly connected or paired to a receiver)."""
    for listener_thread in list(listener._all_listeners.values()):
        receiver = listener_thread.receiver
        if getattr(receiver, "isDevice", False):
            yield receiver
        else:
            yield from receiver


def find_device(dev_id: str):
    device = next((d for d in devices() if device_id(d) == dev_id), None)
    if device is None:
        raise NoSuchDevice(f"no device {dev_id!r}")
    return device


def find_online_device(dev_id: str):
    device = find_device(dev_id)
    if not device.online:
        raise DeviceOffline(f"{dev_id} is offline")
    return device


def describe_device(device) -> dict:
    battery = getattr(device, "battery_info", None)
    return {
        "id": device_id(device),
        "name": device.name,
        "codename": device.codename,
        "kind": str(device.kind),
        "online": bool(device.online),
        "protocol": device.protocol,
        "model_id": device.modelId,
        "unit_id": device.unitId,
        "serial": device.serial,
        "battery": {
            "level": int(battery.level) if battery and battery.level is not None else None,
            "status": battery.status.name if battery and battery.status is not None else None,
        },
    }


def list_devices() -> list[dict]:
    return [describe_device(d) for d in devices()]


# --- settings ---


def _named_ints(values) -> list[dict]:
    return [{"value": int(v), "name": str(v)} for v in values]


def _value_space(space) -> dict:
    if isinstance(space, Range):
        return {"min": space.min, "max": space.max}
    return {"choices": _named_ints(space)}


def _presented_value(setting, value):
    """Scalar kinds can hold a one-entry map (e.g. force-sensing with a single button); present the scalar,
    which is also what their write() accepts."""
    scalar = setting.kind in (Kind.TOGGLE, Kind.CHOICE, Kind.RANGE)
    if scalar and isinstance(value, dict) and len(value) == 1:
        value = next(iter(value.values()))
    return _json_keys(value)


def describe_setting(setting, cached: bool = True) -> dict:
    kind = Kind(setting.kind) if setting.kind is not None else Kind.NONE
    info = {
        "name": setting.name,
        "label": str(setting.label),
        "description": str(setting.description),
        "kind": kind.name,
        "display": getattr(setting, "display", True),
        "writable": kind in WRITABLE_KINDS,
    }
    if kind == Kind.CHOICE:
        info["choices"] = _named_ints(setting.choices)
    elif kind == Kind.RANGE:
        info["min"], info["max"] = setting.range
    elif kind == Kind.MAP_CHOICE:
        info["keys"] = [{"value": int(k), "name": str(k), **_value_space(space)} for k, space in setting.choices.items()]
    try:
        info["value"] = _presented_value(setting, setting.read(cached=cached))
    except Exception as e:  # report but keep listing the other settings
        info["value"] = None
        info["error"] = str(e)
    return info


def find_setting(device, name: str):
    setting = next((s for s in device.settings if s.name == name), None)
    if setting is None:
        raise NoSuchSetting(f"{device_id(device)} has no setting {name!r}")
    return setting


def list_settings(dev_id: str) -> list[dict]:
    return [describe_setting(s) for s in find_device(dev_id).settings]


def _check_choice(value, choices):
    if isinstance(value, str):  # accept a choice name
        match = next((c for c in choices if str(c) == value), None)
        if match is not None:
            return int(match)
    if isinstance(value, int) and not isinstance(value, bool) and value in choices:
        return value
    raise InvalidValue(f"{value!r} is not one of {[str(c) for c in choices]}")


def _check_range(value, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise InvalidValue(f"{value!r} is not an integer in [{low}, {high}]")
    return value


def coerce_value(setting, value):
    """Validate a decoded JSON value for a whole-setting write and convert it to what the setting expects."""
    kind = setting.kind
    if kind == Kind.TOGGLE:
        if not isinstance(value, bool):
            raise InvalidValue(f"{setting.name} needs true or false, not {value!r}")
        return value
    if kind == Kind.CHOICE:
        return _check_choice(value, setting.choices)
    if kind == Kind.RANGE:
        return _check_range(value, *setting.range)
    raise NotSupported(f"{setting.name} ({Kind(kind).name}) cannot be written as a whole through the API")


def coerce_key_value(setting, key, value):
    """Validate a key/value write for a per-key (MAP_CHOICE) setting."""
    if setting.kind != Kind.MAP_CHOICE:
        raise NotSupported(f"{setting.name} is not a per-key setting")
    try:
        ikey = int(key)
    except (TypeError, ValueError) as e:
        raise InvalidValue(f"key {key!r} is not an integer") from e
    space = next((s for k, s in setting.choices.items() if int(k) == ikey), None)
    if space is None:
        raise InvalidValue(f"{setting.name} has no key {key!r}")
    if isinstance(space, Range):
        return ikey, _check_range(value, space.min, space.max)
    return ikey, _check_choice(value, space)


def set_setting(dev_id: str, name: str, value_json: str):
    device = find_online_device(dev_id)
    setting = find_setting(device, name)
    value = coerce_value(setting, from_json(value_json))
    if setting.write(value) is None:
        raise ApiError(f"writing {name} to {dev_id} failed")
    return device, setting


def set_setting_key(dev_id: str, name: str, key_json: str, value_json: str):
    device = find_online_device(dev_id)
    setting = find_setting(device, name)
    key, value = coerce_key_value(setting, from_json(key_json), from_json(value_json))
    if setting.write_key_value(key, value) is None:
        raise ApiError(f"writing {name}[{key}] to {dev_id} failed")
    return device, setting


def play_haptic(dev_id: str, waveform: str) -> None:
    device = find_online_device(dev_id)
    setting = next((s for s in device.settings if s.name == "haptic-play"), None)
    if setting is None:
        raise NotSupported(f"{dev_id} cannot play haptic waveforms")
    value = _check_choice(waveform, setting.choices)
    if setting.write(value, save=False) is None:
        raise ApiError(f"playing {waveform} on {dev_id} failed")


def setting_value(setting):
    """The current cached value of a setting, JSON-ready."""
    return _presented_value(setting, setting.read(cached=True))
