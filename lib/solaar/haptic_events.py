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

"""Haptic feedback on desktop events: which waveform a device plays for which event, and playing it.

Bus-independent: solaar.desktop_events watches the session bus and the daemon reports battery
changes; both end up in HapticEvents.fire(). The mapping event -> waveform is stored per device in
its persister (config.yaml) under _haptic_events. See docs/desktop-events.md.
"""

from __future__ import annotations

import logging
import threading
import time

from logitech_receiver.common import BatteryStatus

from solaar import api
from solaar.i18n import _
from solaar.tasks import TaskRunner

logger = logging.getLogger(__name__)

PERSIST_KEY = "_haptic_events"

NOTIFICATION = "notification"
DESKTOP_SWITCH = "desktop_switch"
BATTERY_LOW = "battery_low"

# in the order front-ends show them
EVENTS = {
    NOTIFICATION: _("New notification"),
    DESKTOP_SWITCH: _("Virtual desktop switched"),
    BATTERY_LOW: _("Battery low"),
}

BATTERY_LOW_LEVEL = 10  # percent: battery_low fires when a battery drops to this level or below
BATTERY_REARM_LEVEL = 15  # percent: and fires again only after the battery went back above this level

MIN_INTERVAL = 0.3  # seconds between two plays on one device, so bursts of events do not buzz continuously


# --- the per-device mapping (front-end API; may talk to the device, so off the main loop) ---


def mapping(device) -> dict:
    """The stored event -> waveform names of a device (empty if none or no persister)."""
    persister = getattr(device, "persister", None)
    stored = persister.get(PERSIST_KEY) if persister else None
    return dict(stored) if isinstance(stored, dict) else {}


def waveforms(device) -> list[str]:
    """Names of the waveforms the device can play, from its haptic-play setting."""
    setting = next((s for s in device.settings if s.name == "haptic-play"), None)
    if setting is None:
        if not device.online:  # settings of a device never seen online cannot be built
            raise api.DeviceOffline(f"{api.device_id(device)} is offline")
        raise api.NotSupported(f"{api.device_id(device)} cannot play haptic waveforms")
    return [str(choice) for choice in setting.choices]


def describe(device) -> dict:
    names = waveforms(device)
    stored = mapping(device)
    return {
        "device_id": api.device_id(device),
        "waveforms": names,
        "events": [{"event": event, "label": str(label), "waveform": stored.get(event)} for event, label in EVENTS.items()],
    }


def get_haptic_events(dev_id: str) -> dict:
    return describe(api.find_device(dev_id))


def set_haptic_event(dev_id: str, event: str, waveform: str) -> dict:
    """Map event to waveform on a device; an empty waveform turns the event off for it."""
    device = api.find_device(dev_id)
    names = waveforms(device)
    if event not in EVENTS:
        raise api.InvalidValue(f"{event!r} is not one of {list(EVENTS)}")
    if waveform and waveform not in names:
        raise api.InvalidValue(f"{waveform!r} is not one of {names}")
    persister = device.persister
    if persister is None:
        raise api.ApiError(f"cannot store settings for {dev_id}")
    stored = mapping(device)
    if waveform:
        stored[event] = waveform
    else:
        stored.pop(event, None)
    persister[PERSIST_KEY] = stored  # a new dict, so readers on other threads see the old or the new one
    logger.info("%s: haptic event %s -> %s", dev_id, event, waveform or "off")
    return describe(device)


# --- playing ---


class HapticEvents:
    """Plays the mapped waveform on every online device when a desktop event fires.

    fire() and battery_changed() run on the main loop; the device writes run on a worker thread.
    Plays are rate-limited per device, and a device whose previous play is still queued (e.g. it
    is asleep and the write is waiting for a timeout) is skipped instead of piling up plays."""

    def __init__(self, devices=None, play=None, worker=None, clock=time.monotonic):
        self._devices = devices or api.devices
        self._play = play or api.play_haptic
        self._worker = worker or TaskRunner("HapticEvents")
        self._clock = clock
        self._last_played = {}  # device id -> clock() of the last play
        self._pending = set()  # device ids with a play queued or running
        self._pending_lock = threading.Lock()  # _pending is shared with the worker
        self._battery_armed = {}  # device id -> battery_low may fire for it

    def start(self):
        self._worker.start()

    def stop(self):
        self._worker.stop()

    def fire(self, event: str):
        """On the main loop: event happened on the desktop."""
        logger.debug("desktop event %s", event)
        now = self._clock()
        for device in list(self._devices()):
            try:
                if not device.online:
                    continue
                waveform = mapping(device).get(event)
                if not waveform:
                    continue
                dev_id = api.device_id(device)
            except Exception:
                logger.debug("cannot check haptic events of %s", device, exc_info=True)
                continue
            last = self._last_played.get(dev_id)
            if last is not None and now - last < MIN_INTERVAL:
                logger.debug("%s: skipping %s for %s, played %.2fs ago", dev_id, waveform, event, now - last)
                continue
            with self._pending_lock:
                if dev_id in self._pending:
                    logger.debug("%s: skipping %s for %s, previous play still pending", dev_id, waveform, event)
                    continue
                self._pending.add(dev_id)
            self._last_played[dev_id] = now
            self._worker(self._play_on, dev_id, waveform, event)

    def _play_on(self, dev_id, waveform, event):
        """On the worker thread."""
        try:
            logger.debug("%s: playing %s for %s", dev_id, waveform, event)
            self._play(dev_id, waveform)
        except api.ApiError as e:
            logger.info("%s: cannot play %s for %s: %s", dev_id, waveform, event, e)
        except Exception:
            logger.warning("%s: playing %s for %s failed", dev_id, waveform, event, exc_info=True)
        finally:
            with self._pending_lock:
                self._pending.discard(dev_id)

    def battery_changed(self, device):
        """On the main loop, after a status change of device: fire battery_low once when its
        battery drops to BATTERY_LOW_LEVEL, and again only after it went back above BATTERY_REARM_LEVEL.

        The event is not tied to the device that plays it: a low keyboard battery can buzz the mouse."""
        info = getattr(device, "battery_info", None)
        level = getattr(info, "level", None)
        if not isinstance(level, int) or info.status == BatteryStatus.OFFLINE:  # unknown, or stale (offline)
            return
        try:
            dev_id = api.device_id(device)
        except Exception:
            return
        if level > BATTERY_REARM_LEVEL:
            self._battery_armed[dev_id] = True
        elif level <= BATTERY_LOW_LEVEL and not info.charging() and self._battery_armed.get(dev_id, True):
            self._battery_armed[dev_id] = False
            logger.info("%s: battery low (%s%%)", dev_id, int(level))
            self.fire(BATTERY_LOW)
