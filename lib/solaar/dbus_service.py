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

"""The plasmaar D-Bus API on the session bus (GDBus), on top of solaar.api.

Every method runs its device work on a worker thread, because HID++ calls block
(tens of milliseconds over Bluetooth, seconds when a device is asleep); the reply
is sent from the main loop. Payloads are JSON strings, described in docs/dbus-api.md.
"""

from __future__ import annotations

import logging

from gi.repository import Gio
from gi.repository import GLib

from solaar import api
from solaar import buttons
from solaar import haptic_events
from solaar import kde_actions
from solaar.tasks import TaskRunner

logger = logging.getLogger(__name__)

BUS_NAME = "io.github.fredaime.Plasmaar"
OBJECT_PATH = "/io/github/fredaime/Plasmaar"
INTERFACE = "io.github.fredaime.Plasmaar1"
ERROR_PREFIX = INTERFACE + ".Error."

INTROSPECTION_XML = f"""
<node>
  <interface name="{INTERFACE}">
    <method name="GetVersion">
      <arg type="s" name="version" direction="out"/>
    </method>
    <method name="ListDevices">
      <arg type="s" name="devices_json" direction="out"/>
    </method>
    <method name="ListSettings">
      <arg type="s" name="device_id" direction="in"/>
      <arg type="s" name="settings_json" direction="out"/>
    </method>
    <method name="SetSetting">
      <arg type="s" name="device_id" direction="in"/>
      <arg type="s" name="name" direction="in"/>
      <arg type="s" name="value_json" direction="in"/>
      <arg type="s" name="value_json" direction="out"/>
    </method>
    <method name="SetSettingKey">
      <arg type="s" name="device_id" direction="in"/>
      <arg type="s" name="name" direction="in"/>
      <arg type="s" name="key_json" direction="in"/>
      <arg type="s" name="value_json" direction="in"/>
      <arg type="s" name="value_json" direction="out"/>
    </method>
    <method name="PlayHaptic">
      <arg type="s" name="device_id" direction="in"/>
      <arg type="s" name="waveform" direction="in"/>
    </method>
    <method name="ListKdeActions">
      <arg type="s" name="actions_json" direction="out"/>
    </method>
    <method name="GetButtonActions">
      <arg type="s" name="device_id" direction="in"/>
      <arg type="s" name="buttons_json" direction="out"/>
    </method>
    <method name="SetButtonAction">
      <arg type="s" name="device_id" direction="in"/>
      <arg type="i" name="control" direction="in"/>
      <arg type="s" name="config_json" direction="in"/>
      <arg type="s" name="button_json" direction="out"/>
    </method>
    <signal name="ButtonActionsChanged">
      <arg type="s" name="device_id"/>
    </signal>
    <signal name="DeviceAdded">
      <arg type="s" name="device_json"/>
    </signal>
    <signal name="DeviceChanged">
      <arg type="s" name="device_json"/>
    </signal>
    <signal name="DeviceRemoved">
      <arg type="s" name="device_id"/>
    </signal>
    <signal name="SettingChanged">
      <arg type="s" name="device_id"/>
      <arg type="s" name="name"/>
      <arg type="s" name="value_json"/>
    </signal>
    <!-- desktop integration (docs/desktop-events.md) -->
    <method name="GetHapticEvents">
      <arg type="s" name="device_id" direction="in"/>
      <arg type="s" name="haptic_events_json" direction="out"/>
    </method>
    <method name="SetHapticEvent">
      <arg type="s" name="device_id" direction="in"/>
      <arg type="s" name="event" direction="in"/>
      <arg type="s" name="waveform" direction="in"/>
      <arg type="s" name="haptic_events_json" direction="out"/>
    </method>
  </interface>
</node>
"""


class Service:
    """Owns the bus name, exports the API object and emits change signals."""

    def __init__(self, on_name_lost=None, connection=None):
        """connection: an existing Gio.DBusConnection to use instead of the session bus (tests)."""
        self._on_name_lost = on_name_lost
        self._given_connection = connection
        self._connection = None
        self._registration_id = None
        self._owner_id = None
        self._known = {}  # device id -> last emitted description
        self._worker = TaskRunner("DBusAPI")
        self._node_info = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION_XML)

    # --- lifecycle ---

    def start(self):
        self._worker.start()
        if self._given_connection is not None:
            self._bus_acquired(self._given_connection, BUS_NAME)
            self._owner_id = Gio.bus_own_name_on_connection(
                self._given_connection, BUS_NAME, Gio.BusNameOwnerFlags.NONE, self._name_acquired, self._name_lost
            )
        else:
            self._owner_id = Gio.bus_own_name(
                Gio.BusType.SESSION,
                BUS_NAME,
                Gio.BusNameOwnerFlags.NONE,
                self._bus_acquired,
                self._name_acquired,
                self._name_lost,
            )

    def stop(self):
        if self._owner_id is not None:
            Gio.bus_unown_name(self._owner_id)
            self._owner_id = None
        if self._connection is not None and self._registration_id is not None:
            self._connection.unregister_object(self._registration_id)
        self._registration_id = None
        self._worker.stop()

    def _bus_acquired(self, connection, _name):
        self._connection = connection
        self._registration_id = connection.register_object(
            OBJECT_PATH, self._node_info.interfaces[0], self._method_call, None, None
        )

    def _name_acquired(self, _connection, name):
        logger.info("D-Bus API available as %s", name)

    def _name_lost(self, _connection, name):
        logger.error("could not own D-Bus name %s (is another plasmaard running?)", name)
        if self._on_name_lost:
            self._on_name_lost()

    # --- method calls ---

    _METHODS = {
        "GetVersion": lambda: f"{api.API_VERSION}",
        "ListDevices": lambda: api.to_json(api.list_devices()),
        "ListSettings": lambda dev_id: api.to_json(api.list_settings(dev_id)),
    }

    def _method_call(self, _connection, _sender, _path, _interface, method, parameters, invocation):
        args = parameters.unpack()
        if self._desktop_method_call(method, args, invocation):
            return
        handler = {
            "SetSetting": self._set_setting,
            "SetSettingKey": self._set_setting_key,
            "PlayHaptic": self._play_haptic,
            "ListKdeActions": self._list_kde_actions,
            "GetButtonActions": self._get_button_actions,
            "SetButtonAction": self._set_button_action,
        }.get(method) or self._METHODS.get(method)
        if handler is None:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", f"no method {method}")
            return
        self._worker(self._run, handler, args, invocation)

    def _run(self, handler, args, invocation):
        """On the worker thread: run the handler, then reply from the main loop."""
        try:
            result = handler(*args)
        except api.ApiError as e:
            GLib.idle_add(_return_error, invocation, ERROR_PREFIX + e.dbus_name, str(e))
        except Exception as e:
            logger.exception("D-Bus method failed")
            GLib.idle_add(_return_error, invocation, ERROR_PREFIX + api.ApiError.dbus_name, str(e))
        else:
            GLib.idle_add(_return_value, invocation, result)

    def _set_setting(self, dev_id, name, value_json):
        _device, setting = api.set_setting(dev_id, name, value_json)
        value = api.to_json(api.setting_value(setting))
        self._emit("SettingChanged", "(sss)", (dev_id, name, value))
        return value

    def _set_setting_key(self, dev_id, name, key_json, value_json):
        _device, setting = api.set_setting_key(dev_id, name, key_json, value_json)
        value = api.to_json(api.setting_value(setting))
        self._emit("SettingChanged", "(sss)", (dev_id, name, value))
        if name == buttons.DIVERT_SETTING:
            self._divert_keys_changed(dev_id, setting)
        return value

    def _play_haptic(self, dev_id, waveform):
        api.play_haptic(dev_id, waveform)
        return None

    # --- button actions (docs/dbus-api.md, solaar.buttons) ---

    def _list_kde_actions(self):
        return api.to_json(kde_actions.list_actions(self._connection))

    def _get_button_actions(self, dev_id):
        return api.to_json(buttons.get_button_actions(dev_id))

    def _set_button_action(self, dev_id, control, config_json):
        button, divert = buttons.set_button_action(dev_id, control, config_json)
        if divert is not None:
            self._emit("SettingChanged", "(sss)", (dev_id, divert.name, api.to_json(api.setting_value(divert))))
        self.button_actions_changed(dev_id)
        return api.to_json(button)

    def _divert_keys_changed(self, dev_id, setting):
        """divert-keys written directly (SetSettingKey): managed button rules follow the new diversion."""
        if buttons.sync_modes(dev_id, setting.read(cached=True)):
            self.button_actions_changed(dev_id)

    def button_actions_changed(self, dev_id):
        """Emit ButtonActionsChanged (any thread), e.g. after buttons.yaml was edited."""
        self._emit("ButtonActionsChanged", "(s)", (dev_id,))

    # --- change notifications from the daemon (any thread) ---

    def device_changed(self, device):
        self._worker(self._describe_and_emit, device)

    def setting_changed(self, device, setting):
        self._worker(self._emit_setting, device, setting)

    def _describe_and_emit(self, device):
        try:
            dev_id = api.device_id(device)
            if not device:  # unpaired: the listener hands over a ghost
                if self._known.pop(dev_id, None) is not None:
                    self._emit("DeviceRemoved", "(s)", (dev_id,))
                return
            description = api.describe_device(device)
        except Exception:
            logger.debug("cannot describe %s", device, exc_info=True)
            return
        signal = "DeviceChanged" if dev_id in self._known else "DeviceAdded"
        if self._known.get(dev_id) != description:
            self._known[dev_id] = description
            self._emit(signal, "(s)", (api.to_json(description),))
        try:  # first sight of the device: record its settings as their defaults (once)
            api.capture_defaults(device)
        except Exception:
            logger.warning("cannot capture the default settings of %s", dev_id, exc_info=True)

    def _emit_setting(self, device, setting):
        try:
            self._emit(
                "SettingChanged", "(sss)", (api.device_id(device), setting.name, api.to_json(api.setting_value(setting)))
            )
        except Exception:
            logger.debug("cannot emit change of %s on %s", setting.name, device, exc_info=True)

    def _emit(self, signal, signature, args):
        if self._connection is None:
            return
        GLib.idle_add(_emit_signal, self._connection, signal, GLib.Variant(signature, args))

    # --- desktop integration: haptic events (docs/desktop-events.md) ---

    _DESKTOP_METHODS = {
        "GetHapticEvents": lambda dev_id: api.to_json(haptic_events.get_haptic_events(dev_id)),
        "SetHapticEvent": lambda dev_id, event, waveform: api.to_json(haptic_events.set_haptic_event(dev_id, event, waveform)),
    }

    def _desktop_method_call(self, method, args, invocation) -> bool:
        """Handle the desktop-integration methods; False if method is not one of them."""
        handler = self._DESKTOP_METHODS.get(method)
        if handler is None:
            return False
        self._worker(self._run, handler, args, invocation)
        return True


def _return_value(invocation, result):
    invocation.return_value(GLib.Variant("(s)", (result,)) if result is not None else None)
    return False


def _return_error(invocation, name, message):
    invocation.return_dbus_error(name, message)
    return False


def _emit_signal(connection, signal, parameters):
    try:
        connection.emit_signal(None, OBJECT_PATH, INTERFACE, signal, parameters)
    except Exception:
        logger.debug("cannot emit %s", signal, exc_info=True)
    return False
