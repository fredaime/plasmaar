## Copyright (C) 2024 Solaar contributors
## Modified for plasmaar since 2026-10-02 (https://github.com/fredaime/plasmaar); dated changes: its git history.
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

"""Desktop notifications through the freedesktop Notifications D-Bus service.

Talks to org.freedesktop.Notifications directly with GDBus (Gio), so it works
headless and needs neither GTK nor libnotify. Plasma, GNOME and most other
desktops implement this service.
"""

import logging

from solaar import APP_ID
from solaar import APP_NAME

logger = logging.getLogger(__name__)

DESKTOP_ENTRY = APP_ID  # share/applications/<APP_ID>.desktop: Plasma shows its name and icon

_BUS_NAME = "org.freedesktop.Notifications"
_OBJECT_PATH = "/org/freedesktop/Notifications"
_INTERFACE = "org.freedesktop.Notifications"
_URGENCY_NORMAL = 1
_CALL_TIMEOUT_MS = 5000

try:
    from gi.repository import Gio
    from gi.repository import GLib

    available = True
except (ImportError, ValueError) as e:
    logger.warning(f"Notification service is not available: {e}")
    available = False

_proxy = None
# notification ids by summary (device name), so a newer notification replaces the visible one
_notifications = {}
_ICON_LISTS = {}


def init():
    """Connect to the notification service on the session bus."""
    global _proxy
    if available and _proxy is None:
        if logger.isEnabledFor(logging.INFO):
            logger.info("starting desktop notifications")
        try:
            _proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION,
                Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES | Gio.DBusProxyFlags.DO_NOT_CONNECT_SIGNALS,
                None,
                _BUS_NAME,
                _OBJECT_PATH,
                _INTERFACE,
                None,
            )
        except Exception:
            logger.warning("cannot connect to the desktop notification service", exc_info=True)
            _proxy = None
    return _proxy is not None


def uninit():
    """Stop desktop notifications."""
    global _proxy
    if _proxy is not None and logger.isEnabledFor(logging.INFO):
        logger.info("stopping desktop notifications")
    _notifications.clear()
    _proxy = None


def show(dev, message: str, icon=None):
    """Show a notification titled with the device name, replacing an earlier one for that device.

    Returns the notification id, or None if no notification was shown."""
    if not (_proxy or init()):
        return None
    summary = dev.name
    icon_name = device_icon_name(dev.name, getattr(dev, "kind", None)) if icon is None else icon
    hints = {
        "desktop-entry": GLib.Variant("s", DESKTOP_ENTRY),
        "urgency": GLib.Variant("y", _URGENCY_NORMAL),
    }
    params = GLib.Variant(
        "(susssasa{sv}i)",
        (APP_NAME, _notifications.get(summary, 0), icon_name or "", summary, message or "", [], hints, -1),
    )
    try:
        reply = _proxy.call_sync("Notify", params, Gio.DBusCallFlags.NONE, _CALL_TIMEOUT_MS, None)
    except Exception:
        logger.warning("showing notification for %s failed", summary, exc_info=True)
        return None
    notification_id = reply.unpack()[0]
    _notifications[summary] = notification_id
    return notification_id


def device_icon_list(name="_", kind=None):
    """Names of possible icons for a device, in increasing order of specificity."""
    icon_list = _ICON_LISTS.get(name)
    if icon_list is None:
        icon_list = ["preferences-desktop-peripherals"]
        if kind is not None:
            kind = str(kind)
            if kind == "numpad":
                icon_list += ("input-keyboard", "input-dialpad")
            elif kind == "touchpad":
                icon_list += ("input-mouse", "input-tablet")
            elif kind == "trackball":
                icon_list += ("input-mouse",)
            elif kind == "headset":
                icon_list += ("audio-headphones", "audio-headset")
            icon_list += (f"input-{kind}",)
        _ICON_LISTS[name] = icon_list
    return icon_list


def device_icon_name(name, kind=None):
    """The most specific icon name; the notification server resolves it against the icon theme."""
    return device_icon_list(name, kind)[-1]
