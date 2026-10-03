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

"""Managed button actions: which KDE action each diverted button of a device runs.

The mappings are kept in $XDG_CONFIG_HOME/plasmaar/buttons.yaml and turned into diversion rules
that run before the user's own rules.yaml, so a managed mapping wins over a custom rule for the
same button. Independent of D-Bus (solaar.dbus_service exposes it); the functions that talk to
a device must run off the main loop.

The file is plain YAML, one entry per device id and button control id:

    B04200000000-BD2BC136:
      416:
        name: Haptic                # informational only
        mode: press                 # off | press | gesture
        press: [kwin, Overview]     # [kglobalaccel component, action name]
      195:
        name: Mouse Gesture Button
        mode: gesture
        gestures:                   # up, down, left, right, click (pressed and released without moving)
          up: [kwin, Grid View]
          down: [kwin, Show Desktop]

Actions for the modes that are not active are kept, so switching back restores them.
"""

from __future__ import annotations

import logging
import os
import threading

import yaml

from logitech_receiver import diversion
from logitech_receiver.special_keys import CONTROL

from solaar import APP_NAME
from solaar import api

logger = logging.getLogger(__name__)

DIVERT_SETTING = "divert-keys"
MODES = {"off": 0, "press": 1, "gesture": 2}  # mode -> divert-keys value: Regular, Diverted, Mouse Gestures
_MODE_OF_VALUE = {value: mode for mode, value in MODES.items()}  # other values (e.g. 3, Sliding DPI) are "off"
DIRECTIONS = {"up": "Mouse Up", "down": "Mouse Down", "left": "Mouse Left", "right": "Mouse Right", "click": None}

_XDG_CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser(os.path.join("~", ".config"))
_file_path = os.path.join(_XDG_CONFIG_HOME, APP_NAME, "buttons.yaml")

_HEADER = (
    "# plasmaar button actions, managed by plasmaard (SetButtonAction on D-Bus, System Settings).\n"
    "# Actions are [kglobalaccel component, action name]. Custom rules belong in rules.yaml.\n"
)

_lock = threading.RLock()
# device id -> {control: {"mode": str, "press": Action | None, "gestures": {direction: Action}}},
# Action = {"component": str, "action": str}
_mappings: dict = {}
_unreadable = False  # the file exists but could not be parsed: keep a backup before replacing it

_KEEP = object()


# --- file ---


class _Dumper(yaml.SafeDumper):
    pass


class _FlowList(list):
    pass


_Dumper.add_representer(_FlowList, lambda dumper, data: dumper.represent_sequence("tag:yaml.org,2002:seq", data, True))


def _action(value):
    """An action written as [component, action] (file) or {"component", "action"}; None if it is not one."""
    if isinstance(value, dict):
        value = (value.get("component"), value.get("action"))
    if isinstance(value, (list, tuple)) and len(value) == 2 and all(isinstance(v, str) and v for v in value):
        return {"component": value[0], "action": value[1]}
    return None


def _is_empty(button) -> bool:
    return button["mode"] == "off" and not button["press"] and not button["gestures"]


def _parse_button(where: str, entry):
    if not isinstance(entry, dict):
        logger.warning("%s: ignoring %s, not a mapping", _file_path, where)
        return None
    mode = entry.get("mode", "off")
    if mode is False:  # YAML 1.1 reads an unquoted off as false
        mode = "off"
    if mode not in MODES:
        logger.warning("%s: %s has unknown mode %r, using off", _file_path, where, mode)
        mode = "off"
    press = _action(entry.get("press"))
    if press is None and entry.get("press") is not None:
        logger.warning("%s: ignoring the press action of %s, not [component, action]", _file_path, where)
    gestures = {}
    raw_gestures = entry.get("gestures") or {}
    if not isinstance(raw_gestures, dict):
        logger.warning("%s: ignoring the gestures of %s, not a mapping", _file_path, where)
        raw_gestures = {}
    for direction, value in raw_gestures.items():
        action = _action(value)
        if direction in DIRECTIONS and action:
            gestures[direction] = action
        elif value is not None:
            logger.warning("%s: ignoring gesture %r of %s", _file_path, direction, where)
    return {"mode": mode, "press": press, "gestures": gestures}


def _parse(data) -> dict:
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("not a mapping of device ids")
    mappings = {}
    for dev_id, device_buttons in data.items():
        if not isinstance(device_buttons, dict):
            logger.warning("%s: ignoring device %s, not a mapping of buttons", _file_path, dev_id)
            continue
        parsed = {}
        for control, entry in device_buttons.items():
            try:
                control = int(control)
            except (TypeError, ValueError):
                logger.warning("%s: ignoring button %r of %s, not a control id", _file_path, control, dev_id)
                continue
            button = _parse_button(f"{dev_id} button {control}", entry)
            if button and not _is_empty(button):
                parsed[control] = button
        if parsed:
            mappings[str(dev_id)] = parsed
    return mappings


def _read(path: str):
    """The mappings in the file: empty when it does not exist, None when it cannot be read or parsed."""
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as config_file:
            return _parse(yaml.safe_load(config_file))
    except Exception as e:
        logger.error("cannot read button actions from %s: %s", path, e)
        return None


def _to_file(mappings) -> dict:
    def button_entry(control, button):
        entry = {"name": str(CONTROL[control]), "mode": button["mode"]}
        if button["press"]:
            entry["press"] = _FlowList([button["press"]["component"], button["press"]["action"]])
        if button["gestures"]:
            entry["gestures"] = {
                direction: _FlowList([action["component"], action["action"]])
                for direction in DIRECTIONS
                for action in [button["gestures"].get(direction)]
                if action
            }
        return entry

    return {
        dev_id: {control: button_entry(control, button) for control, button in sorted(device_buttons.items())}
        for dev_id, device_buttons in sorted(mappings.items())
    }


def _save() -> None:
    """Write the mappings; the caller holds the lock. Failures are logged and the mappings stay active
    for this session, like the device configuration."""
    global _unreadable
    try:
        os.makedirs(os.path.dirname(_file_path), exist_ok=True)
        if _unreadable and os.path.exists(_file_path):
            os.replace(_file_path, _file_path + ".bak")
            logger.warning("replacing the unreadable %s, kept as %s.bak", _file_path, _file_path)
        _unreadable = False
        temporary = _file_path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as config_file:
            config_file.write(_HEADER)
            if _mappings:
                yaml.dump(
                    _to_file(_mappings),
                    config_file,
                    Dumper=_Dumper,
                    default_flow_style=False,
                    sort_keys=False,
                    allow_unicode=True,
                    width=1000,
                )
        os.replace(temporary, _file_path)  # atomic: the file watcher never sees a half-written file
    except OSError as e:
        logger.error("cannot save button actions to %s: %s", _file_path, e)


def reload() -> set:
    """Read the file and regenerate the rules if the mappings changed; returns the ids of the devices
    whose actions changed. An unreadable file (e.g. a broken hand edit) keeps the current mappings."""
    global _mappings, _unreadable
    loaded = _read(_file_path)
    with _lock:
        _unreadable = loaded is None
        if loaded is None:
            return set()
        changed = {dev_id for dev_id in set(loaded) | set(_mappings) if loaded.get(dev_id) != _mappings.get(dev_id)}
        if changed:
            _mappings = loaded
            _apply()
    if changed:
        logger.info("loaded button actions for %s from %s", ", ".join(sorted(changed)), _file_path)
    return changed


# --- rules ---


class _SameDevice(diversion.Condition):
    """Matches the device with this plasmaar device id; for devices that report no unit id."""

    def __init__(self, dev_id: str):
        self.dev_id = dev_id

    def __str__(self):
        return f"Device id: {self.dev_id}"

    def evaluate(self, feature, notification, device, last_result):
        return device is not None and api.device_id(device) == self.dev_id

    def data(self):
        return {"Device": self.dev_id}


def _device_condition(dev_id: str):
    """Scope a rule to one device: by unit id (the Device condition) when the id is <model id>-<unit id>."""
    if "#" not in dev_id and "-" in dev_id:
        return {"Device": dev_id.rsplit("-", 1)[1]}
    return _SameDevice(dev_id)


def generate_rules(mappings) -> diversion.Rule | None:
    """One rule per active mapping: a press runs on [Key: <button>, pressed]; a gesture on
    [MouseGesture: <button>, <direction>], or just the button for a click. Each is scoped to its device."""

    def rule(device, trigger, action):
        shortcut = {"KdeShortcut": [action["component"], action["action"]]}
        return diversion.Rule([device, trigger, shortcut], source=_file_path)

    rules = []
    for dev_id, device_buttons in sorted(mappings.items()):
        device = _device_condition(dev_id)
        for control, button in sorted(device_buttons.items()):
            key = str(CONTROL[control])
            if button["mode"] == "press" and button["press"]:
                rules.append(rule(device, {"Key": [key, diversion.Key.DOWN]}, button["press"]))
            elif button["mode"] == "gesture":
                for direction, movement in DIRECTIONS.items():
                    action = button["gestures"].get(direction)
                    if action:
                        rules.append(rule(device, {"MouseGesture": [key] + ([movement] if movement else [])}, action))
    return diversion.Rule(rules, source=_file_path) if rules else None


def _apply() -> None:
    """Install the rules for the current mappings; the caller holds the lock."""
    diversion.set_generated_rules(generate_rules(_mappings))


# --- API ---


def _divert_setting(device):
    setting = next((s for s in device.settings if s.name == DIVERT_SETTING), None)
    if setting is None:
        raise api.NotSupported(f"{api.device_id(device)} has no divertable buttons")
    return setting


def _divert_values(setting) -> dict:
    try:
        value = setting.read(cached=True)
    except Exception:
        logger.debug("cannot read %s", setting.name, exc_info=True)
        value = None
    return {int(k): v for k, v in value.items()} if isinstance(value, dict) else {}


def _describe_button(dev_id: str, key, choices, divert_value) -> dict:
    """The caller holds the lock."""
    control = int(key)
    allowed = {int(c) for c in choices}
    stored = _mappings.get(dev_id, {}).get(control)
    press = stored["press"] if stored else None
    gestures = stored["gestures"] if stored else {}
    return {
        "control": control,
        "name": str(key),
        "modes": [mode for mode, value in MODES.items() if value in allowed],
        "mode": _MODE_OF_VALUE.get(divert_value, "off"),
        "press": dict(press) if press else None,
        "gestures": {direction: dict(gestures[direction]) if direction in gestures else None for direction in DIRECTIONS},
    }


def get_button_actions(dev_id: str) -> dict:
    """The divertable buttons of a device, how each is diverted, and the actions stored for it."""
    setting = _divert_setting(api.find_device(dev_id))
    values = _divert_values(setting)
    with _lock:
        return {
            "device_id": dev_id,
            "buttons": [
                _describe_button(dev_id, key, choices, values.get(int(key))) for key, choices in setting.choices.items()
            ],
        }


def _api_action(value, where: str):
    if value is None:
        return None
    action = _action(value) if isinstance(value, dict) else None
    if action is None:
        raise api.InvalidValue(f'{where} must be null or {{"component": ..., "action": ...}}, not {value!r}')
    return action


def _api_gestures(value) -> dict:
    if not isinstance(value, dict):
        raise api.InvalidValue(f"gestures must be an object of direction -> action, not {value!r}")
    unknown = sorted(set(value) - set(DIRECTIONS))
    if unknown:
        raise api.InvalidValue(f"unknown gesture directions {unknown}; use {list(DIRECTIONS)}")
    return {direction: _api_action(action, f"gesture {direction}") for direction, action in value.items()}


def set_button_action(dev_id: str, control: int, config_json: str):
    """Set how a button is diverted and which actions it runs.

    config_json: {"mode": "off"|"press"|"gesture", "press": Action|null, "gestures": {direction: Action|null}};
    every field is optional, absent ones are kept, and gestures are merged per direction. A mode is written to
    the divert-keys setting (persisted and re-applied on reconnect), so it needs the device online.
    Returns (the button's description, the divert-keys setting if it was written, else None)."""
    config = api.from_json(config_json)
    if not isinstance(config, dict):
        raise api.InvalidValue(f"button configuration must be a JSON object, not {config_json!r}")
    unknown = sorted(set(config) - {"mode", "press", "gestures"})
    if unknown:
        raise api.InvalidValue(f"unknown button configuration fields {unknown}")
    device = api.find_device(dev_id)
    setting = _divert_setting(device)
    key = next((k for k in setting.choices if int(k) == control), None)
    if key is None:
        raise api.InvalidValue(f"{dev_id} has no divertable button {control}")
    choices = setting.choices[key]
    mode = config.get("mode")
    if "mode" in config:
        if mode not in MODES:
            raise api.InvalidValue(f"mode {mode!r} is not one of {list(MODES)}")
        if MODES[mode] not in {int(c) for c in choices}:
            raise api.NotSupported(f"button {control} ({key}) cannot be set to {mode}")
    press = _api_action(config["press"], "press") if "press" in config else _KEEP
    gestures = _api_gestures(config["gestures"]) if "gestures" in config else {}

    written = None
    if "mode" in config:
        if not device.online:
            raise api.DeviceOffline(f"{dev_id} is offline")
        if setting.write_key_value(int(key), MODES[mode]) is None:
            raise api.ApiError(f"writing {DIVERT_SETTING}[{control}] to {dev_id} failed")
        written = setting
    current = _divert_values(setting).get(int(key))

    with _lock:
        stored = _mappings.get(dev_id, {}).get(int(key))
        button = {"mode": "off", "press": None, "gestures": {}}
        if stored:
            button = {"mode": stored["mode"], "press": stored["press"], "gestures": dict(stored["gestures"])}
        if mode is not None:
            button["mode"] = mode
        elif current is not None:  # the rules follow how the button is diverted
            button["mode"] = _MODE_OF_VALUE.get(current, "off")
        if press is not _KEEP:
            button["press"] = press
        for direction, action in gestures.items():
            if action is None:
                button["gestures"].pop(direction, None)
            else:
                button["gestures"][direction] = action
        device_buttons = dict(_mappings.get(dev_id, {}))
        if _is_empty(button):
            device_buttons.pop(int(key), None)
        else:
            device_buttons[int(key)] = button
        if device_buttons:
            _mappings[dev_id] = device_buttons
        else:
            _mappings.pop(dev_id, None)
        _save()
        _apply()
        return _describe_button(dev_id, key, choices, current), written


def sync_modes(dev_id: str, divert_value) -> bool:
    """Follow divert-keys changes made outside set_button_action (e.g. SetSettingKey): the stored mode decides
    which rules exist, so it must match how each button is diverted. Returns whether anything changed."""
    values = {int(k): v for k, v in divert_value.items()} if isinstance(divert_value, dict) else {}
    with _lock:
        device_buttons = _mappings.get(dev_id)
        if not device_buttons:
            return False
        updated = {
            control: {**button, "mode": _MODE_OF_VALUE.get(values[control], "off")}
            for control, button in device_buttons.items()
            if control in values and button["mode"] != _MODE_OF_VALUE.get(values[control], "off")
        }
        if not updated:
            return False
        _mappings[dev_id] = {**device_buttons, **updated}
        _save()
        _apply()
    return True
