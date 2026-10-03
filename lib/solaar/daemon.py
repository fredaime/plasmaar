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

"""plasmaard: the headless plasmaar service.

Runs the device listener on a GLib main loop without any GUI toolkit. It does
what the GTK application does around the listener, minus the windows:

- discovers receivers and devices and keeps listening for hotplug,
- records setting changes made on the device itself (so saved values follow),
- shows desktop notifications for device alerts,
- pings devices and re-applies settings after resume from suspend,
- saves the configuration and releases devices on SIGTERM/SIGINT,
- exposes the D-Bus API for front-ends (solaar.dbus_service),
- reloads the rules file (button actions, see docs/kde-actions.md) when it changes,
- turns the managed button actions (buttons.yaml, solaar.buttons) into rules and follows their file,
- plays haptic feedback on desktop events: notifications, virtual-desktop switches and low
  batteries (solaar.haptic_events, solaar.desktop_events, docs/desktop-events.md).
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys

import gi

from gi.repository import Gio
from gi.repository import GLib
from logitech_receiver import desktop_notifications
from logitech_receiver import diversion
from logitech_receiver.common import Alert

from solaar import APP_NAME
from solaar import UDEV_RULE
from solaar import __version__
from solaar import buttons
from solaar import configuration
from solaar import dbus
from solaar import dbus_service
from solaar import desktop_events
from solaar import haptic_events
from solaar import listener
from solaar import udev_rule_installed
from solaar.errors import ErrorReason

logger = logging.getLogger(__name__)

try:  # GLib >= 2.80 moved Unix signal sources to GLibUnix; GLib.unix_signal_add is deprecated
    gi.require_version("GLibUnix", "2.0")
    from gi.repository import GLibUnix

    _unix_signal_add = GLibUnix.signal_add
except (ImportError, ValueError, AttributeError):  # older GLib: no GLibUnix, or no signal_add in it
    _unix_signal_add = GLib.unix_signal_add

_LOG_FORMAT = "%(asctime)s,%(msecs)03d %(levelname)8s [%(threadName)s] %(name)s: %(message)s"


class Daemon:
    """Listener callbacks and lifecycle for the headless service.

    The listener invokes the callbacks from its device threads; they are
    marshalled onto the main loop with GLib.idle_add before touching state."""

    def __init__(self, notifications: bool = True, dbus_api: bool = True, haptics: bool = True):
        self.notifications = notifications
        self.loop = GLib.MainLoop()
        self.exit_code = 0
        self.service = dbus_service.Service(on_name_lost=self._name_lost) if dbus_api else None
        # independent of the D-Bus API: the event sources only listen on the session bus
        self.haptic_events = haptic_events.HapticEvents() if haptics else None
        self.desktop_events = desktop_events.DesktopEvents(self._desktop_event) if haptics else None
        self._rules_monitor = None
        self._rules_reload_id = None
        self._buttons_monitor = None
        self._buttons_reload_id = None

    # --- listener callbacks (called from listener threads) ---

    def status_changed(self, device, alert=Alert.NONE, reason=None, refresh=False):
        GLib.idle_add(self._status_changed, device, alert, reason)

    def setting_changed(self, device, setting_class, values):
        GLib.idle_add(self._record_setting, device, setting_class, values)

    def error(self, reason: ErrorReason, object_):
        GLib.idle_add(self._report_error, reason, object_)

    # --- main-loop handlers ---

    def _status_changed(self, device, alert, reason):
        if device is None:
            return False
        alert = Alert.NONE if alert is None else alert
        logger.debug("status changed: %s (%s) %s", device, alert, reason)
        if self.notifications and alert & (Alert.NOTIFICATION | Alert.ATTENTION):
            desktop_notifications.show(device, reason)
        if device.kind is not None:  # receivers have no kind; their devices report separately
            if self.service:
                self.service.device_changed(device)
            if self.haptic_events:
                self.haptic_events.battery_changed(device)
        return False

    def _desktop_event(self, event):
        self.haptic_events.fire(event)

    def _record_setting(self, device, setting_class, values):
        """Record a change made on the device itself; this does not write to the device."""
        setting = next((s for s in device.settings if s.name == setting_class.name), None)
        if setting is None:
            logger.debug("no setting %s on %s to record a change made elsewhere", setting_class.name, device)
            return False
        logger.debug("on %s recording setting %s = %s", device, setting.name, values)
        if len(values) > 1:
            setting.update_key_value(values[0], values[-1])
        else:
            setting.update(values[-1])
        if self.service:
            self.service.setting_changed(device, setting)
        return False

    def _report_error(self, reason: ErrorReason, object_):
        if reason == ErrorReason.PERMISSIONS:
            logger.error("no permission to open %s: install the udev rule %s (make install_udev)", object_, UDEV_RULE)
        else:
            logger.error("%s: %s", reason.value, object_)
        return False

    # --- lifecycle ---

    # --- rules file ---

    def _watch_rules(self):
        """Reload the rules when their file changes (editors often replace it, so watch the path)."""
        try:
            self._rules_monitor = Gio.File.new_for_path(diversion._file_path).monitor_file(
                Gio.FileMonitorFlags.WATCH_MOVES, None
            )
            self._rules_monitor.connect("changed", self._rules_file_changed)
        except Exception:
            logger.warning("cannot watch %s for changes", diversion._file_path, exc_info=True)

    def _rules_file_changed(self, _monitor, _file, _other_file, event):
        if event in (Gio.FileMonitorEvent.ATTRIBUTE_CHANGED, Gio.FileMonitorEvent.CHANGED):
            return  # wait for CHANGES_DONE_HINT, or the create/delete/move that ends the save
        if self._rules_reload_id is None:  # debounce bursts of events from one save
            self._rules_reload_id = GLib.timeout_add(300, self._reload_rules)

    def _reload_rules(self):
        self._rules_reload_id = None
        logger.info("rules file changed, reloading %s", diversion._file_path)
        diversion.reload_config_rule_file()
        return False

    # --- button actions file (solaar.buttons) ---

    def _start_buttons(self):
        """Load the managed button actions, then follow edits of their file (SetButtonAction writes it too)."""
        buttons.reload()
        try:
            self._buttons_monitor = Gio.File.new_for_path(buttons._file_path).monitor_file(
                Gio.FileMonitorFlags.WATCH_MOVES, None
            )
            self._buttons_monitor.connect("changed", self._buttons_file_changed)
        except Exception:
            logger.warning("cannot watch %s for changes", buttons._file_path, exc_info=True)

    def _buttons_file_changed(self, _monitor, _file, _other_file, event):
        if event in (Gio.FileMonitorEvent.ATTRIBUTE_CHANGED, Gio.FileMonitorEvent.CHANGED):
            return  # wait for CHANGES_DONE_HINT, or the create/delete/move that ends the save
        if self._buttons_reload_id is None:  # debounce bursts of events from one save
            self._buttons_reload_id = GLib.timeout_add(300, self._reload_buttons)

    def _reload_buttons(self):
        self._buttons_reload_id = None
        for dev_id in sorted(buttons.reload()):  # nothing when the change was our own write
            if self.service:
                self.service.button_actions_changed(dev_id)
        return False

    def _start(self):
        try:
            listener.start_all()
        except Exception:
            logger.exception("cannot start device listeners")
            self.exit_code = 1
            self.loop.quit()
        return False

    def _name_lost(self):
        self.exit_code = 1
        self.loop.quit()

    def quit(self, *_args):
        logger.info("stopping")
        self.loop.quit()
        return GLib.SOURCE_REMOVE

    def run(self) -> int:
        logger.info("%s daemon %s starting", APP_NAME, __version__)
        if not udev_rule_installed():
            logger.warning("udev rule %s not found: devices are only accessible to root", UDEV_RULE)
        # never connect to the display: GDK exits the process when the compositor restarts
        diversion.allow_display = False
        if self.notifications:
            desktop_notifications.init()
        if self.service:
            self.service.start()
        if self.haptic_events:
            self.haptic_events.start()
            self.desktop_events.start()
        listener.setup_scanner(self.status_changed, self.setting_changed, self.error)
        dbus.watch_suspend_resume(lambda: listener.ping_all(True))
        configuration.defer_saves = True
        self._watch_rules()
        self._start_buttons()
        for signum in (signal.SIGTERM, signal.SIGINT):
            _unix_signal_add(GLib.PRIORITY_HIGH, signum, self.quit)
        GLib.idle_add(self._start)
        try:
            self.loop.run()
        finally:
            if self._rules_monitor is not None:
                self._rules_monitor.cancel()
            if self._buttons_monitor is not None:
                self._buttons_monitor.cancel()
            if self.desktop_events:
                self.desktop_events.stop()
            listener.stop_all()  # also saves the configuration
            if self.haptic_events:
                self.haptic_events.stop()
            if self.service:
                self.service.stop()
            desktop_notifications.uninit()
        return self.exit_code


def _parse_arguments(argv=None):
    parser = argparse.ArgumentParser(
        prog=f"{APP_NAME}d", description=f"{APP_NAME} headless service for Logitech HID++ devices"
    )
    parser.add_argument("-d", "--debug", action="count", default=0, help="print logging messages, -dd for more")
    parser.add_argument("--no-notifications", action="store_true", help="do not show desktop notifications")
    parser.add_argument("--no-dbus", action="store_true", help="do not provide the D-Bus API")
    parser.add_argument("--no-haptic-events", action="store_true", help="do not play haptic feedback on desktop events")
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def _setup_logging(debug: int):
    level = logging.WARNING - 10 * debug
    logging.basicConfig(level=max(level, logging.DEBUG), format=_LOG_FORMAT, stream=sys.stderr)


def main(argv=None) -> int:
    args = _parse_arguments(argv)
    _setup_logging(args.debug)
    return Daemon(notifications=not args.no_notifications, dbus_api=not args.no_dbus, haptics=not args.no_haptic_events).run()


if __name__ == "__main__":
    sys.exit(main())
