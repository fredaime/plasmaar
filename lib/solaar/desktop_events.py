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

"""Desktop events from the session bus, for haptic feedback (solaar.haptic_events).

- "notification": an application asked the notification server to show a notification.
  Nobody broadcasts that, so a separate private connection becomes a bus monitor for the
  org.freedesktop.Notifications.Notify method calls. Only app_name, replaces_id and hints are
  looked at; summaries and bodies are never read or logged.
- "desktop_switch": KWin's org.kde.KWin.VirtualDesktopManager.currentChanged signal.

Each source is optional: a failure is logged and the other one keeps working.
"""

from __future__ import annotations

import logging

from gi.repository import Gio
from gi.repository import GLib
from logitech_receiver.desktop_notifications import DESKTOP_ENTRY

from solaar import APP_NAME

logger = logging.getLogger(__name__)

NOTIFICATION = "notification"
DESKTOP_SWITCH = "desktop_switch"

NOTIFICATIONS_BUS_NAME = "org.freedesktop.Notifications"
NOTIFICATIONS_PATH = "/org/freedesktop/Notifications"
NOTIFICATIONS_INTERFACE = "org.freedesktop.Notifications"
NOTIFY_MATCH_RULE = f"type='method_call',interface='{NOTIFICATIONS_INTERFACE}',member='Notify'"

KWIN_BUS_NAME = "org.kde.KWin"
VIRTUAL_DESKTOPS_PATH = "/VirtualDesktopManager"
VIRTUAL_DESKTOPS_INTERFACE = "org.kde.KWin.VirtualDesktopManager"

_URGENCY_LOW = 0  # Plasma keeps low-urgency notifications out of popups by default
_CALL_TIMEOUT_MS = 1000
_CONNECTION_FLAGS = Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION


def wanted_notification(app_name, replaces_id, hints) -> bool:
    """Whether a Notify call announces a new notification worth a buzz."""
    hints = hints if isinstance(hints, dict) else {}
    if app_name == APP_NAME or hints.get("desktop-entry") == DESKTOP_ENTRY:
        return False  # our own: the device already knows
    if replaces_id:
        return False  # an update of a notification already shown (progress, edited message, ...)
    return hints.get("urgency") != _URGENCY_LOW


class DesktopEvents:
    """Watches the session bus and calls on_event(name) on the main loop.

    connection: a message-bus connection for signals and property reads; default the session bus.
    address: the bus address on which the notification monitor opens its own private connection;
    default the session bus. Tests pass both for a throwaway bus."""

    def __init__(self, on_event, connection=None, address=None):
        self._on_event = on_event
        self._given_connection = connection
        self._address = address
        self._connection = None
        self._monitor = None
        self.monitoring = False  # notifications are being watched
        self._subscription_id = None
        self._cancellable = None

    # --- lifecycle ---

    def start(self):
        self._cancellable = Gio.Cancellable()
        if self._given_connection is not None:
            self._connected(self._given_connection)
        else:
            Gio.bus_get(Gio.BusType.SESSION, self._cancellable, self._bus_got)
        self._open_monitor()

    def stop(self):
        if self._cancellable is not None:
            self._cancellable.cancel()
            self._cancellable = None
        if self._connection is not None and self._subscription_id is not None:
            self._connection.signal_unsubscribe(self._subscription_id)
        self._subscription_id = None
        self._connection = None
        if self._monitor is not None:
            self._close_monitor(self._monitor)

    def _bus_got(self, _source, result):
        try:
            connection = Gio.bus_get_finish(result)
        except GLib.Error as e:
            if not e.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                logger.warning("no session bus, desktop events are not available: %s", e.message)
            return
        self._connected(connection)

    def _connected(self, connection):
        self._connection = connection
        self._subscription_id = connection.signal_subscribe(
            KWIN_BUS_NAME,
            VIRTUAL_DESKTOPS_INTERFACE,
            "currentChanged",
            VIRTUAL_DESKTOPS_PATH,
            None,
            Gio.DBusSignalFlags.NONE,
            self._desktop_changed,
        )
        logger.info("watching virtual desktop switches")

    # --- virtual desktops ---

    def _desktop_changed(self, _connection, _sender, _path, _interface, _signal, _parameters):
        self._on_event(DESKTOP_SWITCH)

    # --- notifications ---

    def _open_monitor(self):
        try:
            address = self._address or Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION, None)
        except GLib.Error as e:
            logger.warning("no session bus, notifications are not watched: %s", e.message)
            return
        Gio.DBusConnection.new_for_address(address, _CONNECTION_FLAGS, None, self._cancellable, self._monitor_connected)

    def _monitor_connected(self, _source, result):
        try:
            monitor = Gio.DBusConnection.new_for_address_finish(result)
        except GLib.Error as e:
            if not e.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                logger.warning("cannot connect to the session bus to watch notifications: %s", e.message)
            return
        if self._cancellable is None:  # stopped meanwhile
            monitor.close_sync(None)
            return
        self._monitor = monitor
        monitor.connect("closed", self._monitor_closed)
        # a monitor must not send anything: the filter swallows the monitored calls, so GDBus does not
        # try to answer them as calls made to us
        monitor.add_filter(self._filter)
        monitor.call(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus.Monitoring",
            "BecomeMonitor",
            GLib.Variant("(asu)", ([NOTIFY_MATCH_RULE], 0)),
            None,
            Gio.DBusCallFlags.NONE,
            -1,
            self._cancellable,
            self._became_monitor,
        )

    def _became_monitor(self, monitor, result):
        try:
            monitor.call_finish(result)
        except GLib.Error as e:
            if not e.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                logger.warning("cannot watch notifications (the bus refused to make plasmaard a monitor): %s", e.message)
                self._close_monitor(monitor)
            return
        self.monitoring = True
        logger.info("watching notifications")

    def _close_monitor(self, monitor):
        if self._monitor is monitor:
            self._monitor = None
            self.monitoring = False
        try:
            monitor.close_sync(None)
        except GLib.Error:
            pass

    def _monitor_closed(self, monitor, remote_peer_vanished, error):
        if remote_peer_vanished and self._monitor is monitor:
            logger.warning("the session bus closed the notification monitor: notifications are no longer watched")
            self._monitor = None
            self.monitoring = False

    def _filter(self, _connection, message, incoming):
        """On a GDBus worker thread: keep the Notify calls for us, pass everything else on."""
        if (
            not incoming
            or message.get_message_type() != Gio.DBusMessageType.METHOD_CALL
            or message.get_interface() != NOTIFICATIONS_INTERFACE
            or message.get_member() != "Notify"
        ):
            return message
        try:
            app_name, replaces_id, _icon, _summary, _body, _actions, hints, _timeout = message.get_body().unpack()
        except Exception:
            logger.debug("malformed Notify call", exc_info=True)
            return None
        if wanted_notification(app_name, replaces_id, hints):
            GLib.idle_add(self._notified, app_name)
        return None

    def _notified(self, app_name):
        """On the main loop: a new notification; skip it while Do Not Disturb is on."""
        logger.debug("notification from %s", app_name)
        if self._connection is None:
            self._on_event(NOTIFICATION)
            return False
        self._connection.call(
            NOTIFICATIONS_BUS_NAME,
            NOTIFICATIONS_PATH,
            "org.freedesktop.DBus.Properties",
            "Get",
            GLib.Variant("(ss)", (NOTIFICATIONS_INTERFACE, "Inhibited")),
            GLib.VariantType("(v)"),
            Gio.DBusCallFlags.NO_AUTO_START,
            _CALL_TIMEOUT_MS,
            self._cancellable,
            self._got_inhibited,
        )
        return False

    def _got_inhibited(self, connection, result):
        try:
            (inhibited,) = connection.call_finish(result).unpack()
        except GLib.Error as e:
            if e.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                return
            inhibited = False  # a notification server without the (optional) Inhibited property
            logger.debug("cannot read Inhibited from the notification server: %s", e.message)
        if inhibited:
            logger.debug("notification during Do Not Disturb: no haptic feedback")
        else:
            self._on_event(NOTIFICATION)
