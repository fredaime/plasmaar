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

"""The KDE global-shortcut actions a button can run, read from kglobalaccel.

Lists every component's actions with their localized names, for pickers in front-ends. The names
are the ones the KdeShortcut rule action and SetButtonAction take. Blocking D-Bus calls: run it off
the main loop. The connection is passed in, so tests can point it at a private bus.
"""

from __future__ import annotations

import logging
import unicodedata

from gi.repository import Gio
from gi.repository import GLib

from solaar import api

logger = logging.getLogger(__name__)

KGLOBALACCEL = "org.kde.kglobalaccel"
KGLOBALACCEL_PATH = "/kglobalaccel"
KGLOBALACCEL_INTERFACE = "org.kde.KGlobalAccel"
COMPONENT_INTERFACE = "org.kde.kglobalaccel.Component"
_PROPERTIES_INTERFACE = "org.freedesktop.DBus.Properties"
_DEFAULT_CONTEXT = "default"
_HIDDEN_ACTIONS = {"_k_friendly_name"}  # older kglobalaccel stored the component's name as a pseudo action
TIMEOUT_MS = 3000


def _call(connection, path, interface, method, parameters, reply_type):
    reply = connection.call_sync(
        KGLOBALACCEL,
        path,
        interface,
        method,
        parameters,
        GLib.VariantType(reply_type),
        Gio.DBusCallFlags.NO_AUTO_START,  # listing must not launch a kglobalaccel outside the Plasma session
        TIMEOUT_MS,
        None,
    )
    return reply.unpack()


def _sort_key(text: str):
    """Case- and accent-insensitive, so "Écran" sorts with "ecran", whatever the process locale."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold(), text


def _read_component(connection, path: str):
    """(unique name, label, [(action name, action label)]) of one component, default context only."""
    try:
        (properties,) = _call(
            connection, path, _PROPERTIES_INTERFACE, "GetAll", GLib.Variant("(s)", (COMPONENT_INTERFACE,)), "(a{sv})"
        )
    except GLib.Error as e:  # the shortcut infos carry the component names too
        logger.debug("no properties for %s: %s", path, e)
        properties = {}
    (infos,) = _call(connection, path, COMPONENT_INTERFACE, "allShortcutInfos", None, "(a(ssssssaiai))")
    name = properties.get("uniqueName") or next((info[2] for info in infos if info[2]), "")
    label = properties.get("friendlyName") or next((info[3] for info in infos if info[3]), "") or name
    actions = [
        (info[0], info[1] or info[0])
        for info in infos
        if info[0] and info[0] not in _HIDDEN_ACTIONS and info[4] in ("", _DEFAULT_CONTEXT)
    ]
    return name, label, actions


def list_actions(connection) -> list[dict]:
    """[{"component", "label", "actions": [{"name", "label"}]}] for every component that has actions, sorted by
    label; a component that cannot be read is skipped."""
    if connection is None:
        raise api.ApiError("not connected to the session bus")
    try:
        (paths,) = _call(connection, KGLOBALACCEL_PATH, KGLOBALACCEL_INTERFACE, "allComponents", None, "(ao)")
    except GLib.Error as e:
        raise api.ApiError(f"cannot list KDE global shortcuts (is kglobalaccel running?): {e.message}") from e

    components = {}  # unique name -> (label, {action name: action label})
    for path in paths:
        try:
            name, label, actions = _read_component(connection, path)
        except GLib.Error as e:
            logger.warning("cannot list the KDE actions of %s: %s", path, e.message)
            continue
        if not name:
            continue
        _label, known = components.setdefault(name, (label, {}))
        for action, action_label in actions:
            known.setdefault(action, action_label)

    listed = [
        {
            "component": name,
            "label": label,
            "actions": sorted(
                ({"name": action, "label": action_label} for action, action_label in actions.items()),
                key=lambda a: (_sort_key(a["label"]), a["name"]),
            ),
        }
        for name, (label, actions) in components.items()
        if actions
    ]
    return sorted(listed, key=lambda c: (_sort_key(c["label"]), c["component"]))
