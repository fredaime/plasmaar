#!/usr/bin/env python3
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

"""A fake plasmaard for developing and testing D-Bus clients (the System Settings module) without hardware.

It implements the whole io.github.fredaime.Plasmaar1 contract (docs/dbus-api.md plus the button-action and
haptic-event additions) with data captured from a real MX Master 4, K850 and MX Anywhere 3S
(tools/mock_plasmaard_data.json). State is mutable in memory and every change emits the same signals as the
real service. It owns the bus name on whatever bus DBUS_SESSION_BUS_ADDRESS points to, so run it inside an
isolated bus:

    dbus-run-session -- bash -c 'python3 tools/mock_plasmaard.py & sleep 1; kcmshell6 kcm_plasmaar'

It refuses to start when the name is already owned (the real plasmaard on your session bus).

A second interface, io.github.fredaime.PlasmaarMock, lets tests simulate changes made on the device itself:
SetDeviceValue(id, name, value_json), SetOnline(id, online), SetBattery(id, level); and Quit() (the service
going away).
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys

from gi.repository import Gio
from gi.repository import GLib

BUS_NAME = "io.github.fredaime.Plasmaar"
OBJECT_PATH = "/io/github/fredaime/Plasmaar"
INTERFACE = "io.github.fredaime.Plasmaar1"
MOCK_INTERFACE = "io.github.fredaime.PlasmaarMock"
ERROR_PREFIX = INTERFACE + ".Error."

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(HERE, "mock_plasmaard_data.json")
PO_DIR = os.path.join(os.path.dirname(HERE), "po")

MX4 = "B04200000000-BD2BC136"
K850 = "B34D40620000-FF883310"
MX3S = "B03700000000-3F51C045"

# Values that differ from what the real devices reported, so that "Defaults" has something to do, and the
# value plasmaard captured when it first saw each device ("default"). Settings not listed keep their current
# value as default; change-host and haptic-play have none (absent, as for a setting plasmaard never saw).
CURRENT_OVERRIDES = {MX4: {"dpi": 1600, "haptic-level": 80, "scroll-ratchet-torque": 60}}
DEFAULT_OVERRIDES = {
    MX4: {
        "dpi": 1000,
        "haptic-level": 100,
        "smart-shift": 10,
        "divert-keys": {k: 0 for k in ("82", "83", "86", "195", "196", "416")},
    },
    K850: {"fn-swap": True},
}
NO_DEFAULT = {"change-host", "haptic-play"}

V1_METHODS = """
    <method name="GetVersion"><arg type="s" name="version" direction="out"/></method>
    <method name="ListDevices"><arg type="s" name="devices_json" direction="out"/></method>
    <method name="ListSettings">
      <arg type="s" name="device_id" direction="in"/><arg type="s" name="settings_json" direction="out"/>
    </method>
    <method name="SetSetting">
      <arg type="s" name="device_id" direction="in"/><arg type="s" name="name" direction="in"/>
      <arg type="s" name="value_json" direction="in"/><arg type="s" name="value_json" direction="out"/>
    </method>
    <method name="SetSettingKey">
      <arg type="s" name="device_id" direction="in"/><arg type="s" name="name" direction="in"/>
      <arg type="s" name="key_json" direction="in"/><arg type="s" name="value_json" direction="in"/>
      <arg type="s" name="value_json" direction="out"/>
    </method>
    <method name="PlayHaptic">
      <arg type="s" name="device_id" direction="in"/><arg type="s" name="waveform" direction="in"/>
    </method>
    <signal name="DeviceAdded"><arg type="s" name="device_json"/></signal>
    <signal name="DeviceChanged"><arg type="s" name="device_json"/></signal>
    <signal name="DeviceRemoved"><arg type="s" name="device_id"/></signal>
    <signal name="SettingChanged">
      <arg type="s" name="device_id"/><arg type="s" name="name"/><arg type="s" name="value_json"/>
    </signal>
"""
ADDED_METHODS = """
    <method name="ListKdeActions"><arg type="s" name="actions_json" direction="out"/></method>
    <method name="GetButtonActions">
      <arg type="s" name="device_id" direction="in"/><arg type="s" name="buttons_json" direction="out"/>
    </method>
    <method name="SetButtonAction">
      <arg type="s" name="device_id" direction="in"/><arg type="i" name="control" direction="in"/>
      <arg type="s" name="config_json" direction="in"/><arg type="s" name="button_json" direction="out"/>
    </method>
    <method name="GetHapticEvents">
      <arg type="s" name="device_id" direction="in"/><arg type="s" name="events_json" direction="out"/>
    </method>
    <method name="SetHapticEvent">
      <arg type="s" name="device_id" direction="in"/><arg type="s" name="event" direction="in"/>
      <arg type="s" name="waveform" direction="in"/><arg type="s" name="event_json" direction="out"/>
    </method>
    <signal name="ButtonActionsChanged"><arg type="s" name="device_id"/></signal>
"""
MOCK_METHODS = f"""
  <interface name="{MOCK_INTERFACE}">
    <method name="SetDeviceValue">
      <arg type="s" name="device_id" direction="in"/><arg type="s" name="name" direction="in"/>
      <arg type="s" name="value_json" direction="in"/>
    </method>
    <method name="SetOnline">
      <arg type="s" name="device_id" direction="in"/><arg type="b" name="online" direction="in"/>
    </method>
    <method name="SetBattery">
      <arg type="s" name="device_id" direction="in"/><arg type="i" name="level" direction="in"/>
    </method>
    <method name="Quit"/>
  </interface>
"""

ADDED_NAMES = {"ListKdeActions", "GetButtonActions", "SetButtonAction", "GetHapticEvents", "SetHapticEvent"}
DIRECTIONS = ("up", "down", "left", "right", "click")
EVENT_LABELS = {
    "notification": ("New notification", "Nouvelle notification"),
    "desktop_switch": ("Virtual desktop switch", "Changement de bureau virtuel"),
    "battery_low": ("Low battery", "Batterie faible"),
}


class ApiError(Exception):
    def __init__(self, name, message):
        super().__init__(message)
        self.dbus_name = name


def log(*args):
    print("mock_plasmaard:", *args, file=sys.stderr, flush=True)


# --- translations, so that labels come "already localized" as from the real service ---


def _language():
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if value:
            return value.split(":")[0].split(".")[0].split("_")[0]
    return "en"


def _po_catalog(lang):
    path = os.path.join(PO_DIR, f"{lang}.po")
    catalog = {}
    if not os.path.exists(path):
        return catalog
    msgid = msgstr = None
    target = None

    def unquote(text):
        return json.loads(text) if text.startswith('"') else ""

    def flush():
        if msgid and msgstr:
            catalog[msgid] = msgstr

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("msgid "):
                flush()
                msgid, msgstr, target = unquote(line[6:]), None, "id"
            elif line.startswith("msgstr "):
                msgstr, target = unquote(line[7:]), "str"
            elif line.startswith('"') and target == "id":
                msgid += unquote(line)
            elif line.startswith('"') and target == "str":
                msgstr += unquote(line)
            elif not line or line.startswith("#"):
                target = None
    flush()
    return catalog


class Translator:
    def __init__(self, lang):
        self.lang = lang
        self.catalog = _po_catalog(lang) if lang != "en" else {}

    def __call__(self, text):
        if not self.catalog or not isinstance(text, str):
            return text
        if text in self.catalog:
            return self.catalog[text]
        # descriptions are several messages joined by newlines
        parts = re.split(r"(\n+)", text)
        return "".join(self.catalog.get(p, p) for p in parts)


# --- the fake devices ---


def _expand_choices(choices, shared):
    if isinstance(choices, str):
        return shared[choices]
    if isinstance(choices, dict) and "numeric" in choices:
        low, high, step = choices["numeric"]
        return [{"value": v, "name": str(v)} for v in range(low, high + 1, step)]
    return choices


class Device:
    def __init__(self, description, settings, shared, tr):
        self.info = copy.deepcopy(description)
        self.settings = {}
        for s in settings:
            s = copy.deepcopy(s)
            s["label"], s["description"] = tr(s["label"]), tr(s["description"])
            if "choices" in s:
                s["choices"] = [{**c, "name": tr(c["name"])} for c in _expand_choices(s["choices"], shared)]
            for key in s.get("keys", []):
                key["name"] = tr(key["name"])
                if "choices" in key:
                    key["choices"] = [{**c, "name": tr(c["name"])} for c in _expand_choices(key["choices"], shared)]
            self.settings[s["name"]] = s
        dev_id = self.id
        for name, value in CURRENT_OVERRIDES.get(dev_id, {}).items():
            self.settings[name]["value"] = value
        for name, s in self.settings.items():
            if name in NO_DEFAULT or s["value"] is None:
                continue
            s["default"] = copy.deepcopy(DEFAULT_OVERRIDES.get(dev_id, {}).get(name, s["value"]))
        self.buttons = self._initial_buttons()
        self.haptic_events = self._initial_haptic_events(tr)

    @property
    def id(self):
        return self.info["id"]

    def waveforms(self):
        play = self.settings.get("haptic-play")
        return [c["name"] for c in play["choices"]] if play else []

    def _initial_buttons(self):
        divert = self.settings.get("divert-keys")
        if not divert:
            return []
        buttons = []
        for key in divert["keys"]:
            names = {c["value"] for c in key["choices"]}
            modes = ["off"] + (["press"] if 1 in names else []) + (["gesture"] if 2 in names else [])
            buttons.append(
                {
                    "control": key["value"],
                    "name": key["name"],
                    "modes": modes,
                    "mode": "off",
                    "press": None,
                    "gestures": {d: None for d in DIRECTIONS},
                }
            )
        if self.id == MX4:  # what docs/kde-actions.md sets up
            by_control = {b["control"]: b for b in buttons}
            by_control[416].update(mode="press", press={"component": "kwin", "action": "Overview"})
            by_control[195]["mode"] = "gesture"
            by_control[195]["gestures"].update(
                up={"component": "kwin", "action": "Grid View"},
                down={"component": "kwin", "action": "Show Desktop"},
                left={"component": "kwin", "action": "Switch One Desktop to the Left"},
                right={"component": "kwin", "action": "Switch One Desktop to the Right"},
            )
        return buttons

    def _initial_haptic_events(self, tr):
        if not self.waveforms():
            return []
        lang_fr = tr.lang == "fr"
        initial = {"notification": "SUBTLE COLLISION", "desktop_switch": "SHARP STATE CHANGE", "battery_low": None}
        return [
            {"event": event, "label": labels[1] if lang_fr else labels[0], "waveform": initial[event]}
            for event, labels in EVENT_LABELS.items()
        ]

    def public_settings(self, with_defaults):
        result = []
        for s in self.settings.values():
            s = copy.deepcopy(s)
            if not with_defaults:
                s.pop("default", None)
            if not self.info["online"] and s["value"] is None:
                s["error"] = "device is offline"
            result.append(s)
        return result


def _check_choice(value, choices):
    if isinstance(value, str):
        match = next((c for c in choices if c["name"] == value), None)
        if match is not None:
            return match["value"]
    if isinstance(value, int) and not isinstance(value, bool) and any(c["value"] == value for c in choices):
        return value
    raise ApiError("InvalidValue", f"{value!r} is not one of {[c['name'] for c in choices][:10]}")


def _check_range(value, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ApiError("InvalidValue", f"{value!r} is not an integer in [{low}, {high}]")
    return value


def _from_json(text):
    try:
        return json.loads(text)
    except (TypeError, ValueError) as e:
        raise ApiError("InvalidValue", f"not valid JSON: {text!r}") from e


def _to_json(value):
    return json.dumps(value)


class MockService:
    def __init__(self, args):
        self.args = args
        tr = Translator(_language())
        with open(DATA_FILE, encoding="utf-8") as f:
            data = json.load(f)
        self.devices = {}
        for entry in data["devices"]:
            device = Device(entry["device"], entry["settings"], data["shared_choices"], tr)
            self.devices[device.id] = device
        # MX Anywhere 3S sits in a drawer: offline, battery unknown
        mx3s = self.devices.get(MX3S)
        if mx3s:
            mx3s.info.update(online=False, battery={"level": None, "status": None})
        self.kde_actions = data["kde_actions"]
        if tr.lang != "fr":  # the captured labels are French; elsewhere show the action ids
            for component in self.kde_actions:
                for action in component["actions"]:
                    action["label"] = action["name"]
        self.connection = None
        self.loop = None
        xml = "<node>\n  <interface name='%s'>%s%s</interface>%s</node>" % (
            INTERFACE,
            V1_METHODS,
            "" if args.legacy else ADDED_METHODS,
            MOCK_METHODS,
        )
        self.node_info = Gio.DBusNodeInfo.new_for_xml(xml)

    # --- bus plumbing ---

    def start(self, loop):
        self.loop = loop

        def acquired(connection, _name):
            self.connection = connection
            for interface in self.node_info.interfaces:
                connection.register_object(OBJECT_PATH, interface, self._method_call, None, None)

        def name_acquired(_connection, name):
            log(f"serving {name} ({'v1 only' if self.args.legacy else 'v1 + additions'}) with", len(self.devices), "devices")

        def name_lost(_connection, name):
            log(f"cannot own {name}: is plasmaard already running on this bus? Run me inside dbus-run-session.")
            loop.quit()

        Gio.bus_own_name(Gio.BusType.SESSION, BUS_NAME, Gio.BusNameOwnerFlags.DO_NOT_QUEUE, acquired, name_acquired, name_lost)

    def emit(self, signal, signature, args):
        if self.args.verbose:
            log("signal", signal, args)
        self.connection.emit_signal(None, OBJECT_PATH, INTERFACE, signal, GLib.Variant(signature, args))

    def _method_call(self, _connection, _sender, _path, interface, method, parameters, invocation):
        handler = getattr(self, ("mock_" if interface == MOCK_INTERFACE else "do_") + method, None)
        if handler is None or (self.args.legacy and method in ADDED_NAMES):
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", f"no method {method}")
            return
        args = parameters.unpack()
        if self.args.verbose:
            log("call", method, *(a if len(str(a)) < 120 else str(a)[:120] + "…" for a in args))

        def reply():
            try:
                result = handler(*args)
            except ApiError as e:
                invocation.return_dbus_error(ERROR_PREFIX + e.dbus_name, str(e))
            else:
                invocation.return_value(GLib.Variant("(s)", (result,)) if result is not None else None)
            return False

        if self.args.delay and method not in ("GetVersion",):
            GLib.timeout_add(self.args.delay, reply)
        else:
            reply()

    def device(self, dev_id, online=False):
        device = self.devices.get(dev_id)
        if device is None:
            raise ApiError("NoSuchDevice", f"no device {dev_id!r}")
        if online and not device.info["online"]:
            raise ApiError("DeviceOffline", f"{dev_id} is offline")
        return device

    def setting(self, device, name):
        setting = device.settings.get(name)
        if setting is None:
            raise ApiError("NoSuchSetting", f"{device.id} has no setting {name!r}")
        return setting

    def check_failure(self, name):
        if name in self.args.fail:
            raise ApiError("Failed", f"writing {name} failed (simulated by mock_plasmaard --fail)")

    # --- v1 ---

    def do_GetVersion(self):
        return "1"

    def do_ListDevices(self):
        return _to_json([d.info for d in self.devices.values()])

    def do_ListSettings(self, dev_id):
        return _to_json(self.device(dev_id).public_settings(with_defaults=not self.args.legacy))

    def do_SetSetting(self, dev_id, name, value_json):
        device = self.device(dev_id, online=True)
        setting = self.setting(device, name)
        value = _from_json(value_json)
        kind = setting["kind"]
        if kind == "TOGGLE":
            if not isinstance(value, bool):
                raise ApiError("InvalidValue", f"{name} needs true or false, not {value!r}")
        elif kind == "CHOICE":
            value = _check_choice(value, setting["choices"])
        elif kind == "RANGE":
            value = _check_range(value, setting["min"], setting["max"])
        else:
            raise ApiError("NotSupported", f"{name} ({kind}) cannot be written as a whole through the API")
        self.check_failure(name)
        setting["value"] = value
        self.emit("SettingChanged", "(sss)", (dev_id, name, _to_json(value)))
        return _to_json(value)

    def do_SetSettingKey(self, dev_id, name, key_json, value_json):
        device = self.device(dev_id, online=True)
        setting = self.setting(device, name)
        if setting["kind"] != "MAP_CHOICE":
            raise ApiError("NotSupported", f"{name} is not a per-key setting")
        key = _from_json(key_json)
        try:
            key = int(key)
        except (TypeError, ValueError) as e:
            raise ApiError("InvalidValue", f"key {key!r} is not an integer") from e
        space = next((k for k in setting["keys"] if k["value"] == key), None)
        if space is None:
            raise ApiError("InvalidValue", f"{name} has no key {key!r}")
        value = _from_json(value_json)
        if "choices" in space:
            value = _check_choice(value, space["choices"])
        else:
            value = _check_range(value, space["min"], space["max"])
        self.check_failure(name)
        setting["value"][str(key)] = value
        self.emit("SettingChanged", "(sss)", (dev_id, name, _to_json(setting["value"])))
        if name == "divert-keys":
            self._sync_button_mode(device, key, value)
        return _to_json(setting["value"])

    def do_PlayHaptic(self, dev_id, waveform):
        device = self.device(dev_id, online=True)
        if not device.waveforms():
            raise ApiError("NotSupported", f"{dev_id} cannot play haptic waveforms")
        if waveform not in device.waveforms():
            raise ApiError("InvalidValue", f"{waveform!r} is not one of {device.waveforms()}")
        log(f"*bzz* {device.info['name']} plays {waveform}")
        return None

    # --- additions ---

    def do_ListKdeActions(self):
        return _to_json(self.kde_actions)

    def do_GetButtonActions(self, dev_id):
        device = self.device(dev_id)
        return _to_json({"device_id": dev_id, "buttons": device.buttons})

    def do_SetButtonAction(self, dev_id, control, config_json):
        device = self.device(dev_id)
        button = next((b for b in device.buttons if b["control"] == control), None)
        if button is None:
            raise ApiError("InvalidValue", f"{dev_id} has no divertable button {control}")
        config = _from_json(config_json)
        if not isinstance(config, dict) or config.get("mode") not in button["modes"]:
            raise ApiError("InvalidValue", f"mode must be one of {button['modes']}")

        def action(value):
            if value is None:
                return None
            if not isinstance(value, dict) or not value.get("component") or not value.get("action"):
                raise ApiError("InvalidValue", f"an action is {{'component': …, 'action': …}} or null, not {value!r}")
            return {"component": str(value["component"]), "action": str(value["action"])}

        press = action(config.get("press"))
        gestures = config.get("gestures") or {}
        if not isinstance(gestures, dict) or set(gestures) - set(DIRECTIONS):
            raise ApiError("InvalidValue", f"gestures takes the directions {DIRECTIONS}")
        gestures = {d: action(gestures.get(d)) for d in DIRECTIONS}
        self.check_failure(f"button:{control}")
        button.update(mode=config["mode"], press=press, gestures=gestures)
        divert = device.settings.get("divert-keys")
        wanted = {"off": 0, "press": 1, "gesture": 2}[button["mode"]]
        if divert and divert["value"].get(str(control)) != wanted:
            divert["value"][str(control)] = wanted
            self.emit("SettingChanged", "(sss)", (dev_id, "divert-keys", _to_json(divert["value"])))
        self.emit("ButtonActionsChanged", "(s)", (dev_id,))
        return _to_json(button)

    def _sync_button_mode(self, device, control, divert_value):
        button = next((b for b in device.buttons if b["control"] == control), None)
        mode = {0: "off", 1: "press", 2: "gesture"}.get(divert_value, "off")
        if button and button["mode"] != mode and mode in button["modes"]:
            button["mode"] = mode
            self.emit("ButtonActionsChanged", "(s)", (device.id,))

    def do_GetHapticEvents(self, dev_id):
        device = self.device(dev_id)
        if not device.haptic_events:
            raise ApiError("NotSupported", f"{dev_id} has no haptic motor")
        return _to_json({"device_id": dev_id, "waveforms": device.waveforms(), "events": device.haptic_events})

    def do_SetHapticEvent(self, dev_id, event, waveform):
        device = self.device(dev_id)
        entry = next((e for e in device.haptic_events if e["event"] == event), None)
        if entry is None:
            raise ApiError("InvalidValue", f"{dev_id} has no haptic event {event!r}")
        if waveform and waveform not in device.waveforms():
            raise ApiError("InvalidValue", f"{waveform!r} is not one of {device.waveforms()}")
        self.check_failure(f"haptic:{event}")
        entry["waveform"] = waveform or None
        return _to_json(entry)

    # --- test hooks: changes "made on the device" ---

    def mock_SetDeviceValue(self, dev_id, name, value_json):
        device = self.device(dev_id)
        setting = self.setting(device, name)
        setting["value"] = _from_json(value_json)
        self.emit("SettingChanged", "(sss)", (dev_id, name, _to_json(setting["value"])))

    def mock_SetOnline(self, dev_id, online):
        device = self.device(dev_id)
        device.info["online"] = bool(online)
        self.emit("DeviceChanged", "(s)", (_to_json(device.info),))

    def mock_SetBattery(self, dev_id, level):
        device = self.device(dev_id)
        device.info["battery"] = {"level": level, "status": "DISCHARGING"} if level >= 0 else {"level": None, "status": None}
        self.emit("DeviceChanged", "(s)", (_to_json(device.info),))

    def mock_Quit(self):
        log("quitting")
        GLib.timeout_add(50, self.loop.quit)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--legacy", action="store_true", help="v1 API only, like a plasmaard without the additions")
    parser.add_argument(
        "--fail",
        action="append",
        default=[],
        metavar="NAME",
        help="make writes of this setting fail (also button:<control>, haptic:<event>); repeatable",
    )
    parser.add_argument("--delay", type=int, default=0, metavar="MS", help="answer every call after MS milliseconds")
    parser.add_argument("--verbose", "-v", action="store_true", help="log calls and signals")
    args = parser.parse_args(argv)
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        log("DBUS_SESSION_BUS_ADDRESS is not set; run me inside dbus-run-session")
        return 2
    loop = GLib.MainLoop()
    MockService(args).start(loop)
    try:
        loop.run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
