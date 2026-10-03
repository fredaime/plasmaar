import logging

from types import SimpleNamespace
from unittest import mock

import pytest
import yaml

from logitech_receiver.common import Battery
from logitech_receiver.common import BatteryLevelApproximation
from logitech_receiver.common import BatteryStatus
from logitech_receiver.common import NamedInts
from solaar import api
from solaar import configuration
from solaar import haptic_events

WAVEFORMS = NamedInts(SHARP_STATE_CHANGE=0x00, HAPPY_ALERT=0x05, WAVE=0x09)


def _haptic_play():
    setting = mock.Mock(choices=WAVEFORMS)
    setting.name = "haptic-play"
    return setting


def _device(dev_id="B042-1", online=True, haptics=True, stored=None, persister=True):
    entry = configuration._DeviceEntry()
    if stored is not None:
        dict.__setitem__(entry, haptic_events.PERSIST_KEY, stored)
    return SimpleNamespace(
        id=dev_id,
        online=online,
        settings=[_haptic_play()] if haptics else [],
        persister=entry if persister else None,
        battery_info=None,
    )


@pytest.fixture(autouse=True)
def device_ids(monkeypatch):
    monkeypatch.setattr(api, "device_id", lambda device: device.id)


@pytest.fixture
def no_saves(monkeypatch):
    save = mock.Mock(name="save")
    monkeypatch.setattr(configuration, "save", save)
    return save


@pytest.fixture
def find(monkeypatch):
    devices = {}

    def find_device(dev_id):
        if dev_id not in devices:
            raise api.NoSuchDevice(f"no device {dev_id!r}")
        return devices[dev_id]

    monkeypatch.setattr(api, "find_device", find_device)
    return devices


# --- mapping and the front-end API ---


def test_get_haptic_events_describes_events_and_waveforms(find):
    find["B042-1"] = _device(stored={"notification": "WAVE"})

    assert haptic_events.get_haptic_events("B042-1") == {
        "device_id": "B042-1",
        "waveforms": ["SHARP STATE CHANGE", "HAPPY ALERT", "WAVE"],
        "events": [
            {"event": "notification", "label": "New notification", "waveform": "WAVE"},
            {"event": "desktop_switch", "label": "Virtual desktop switched", "waveform": None},
            {"event": "battery_low", "label": "Battery low", "waveform": None},
        ],
    }


def test_get_haptic_events_unknown_device(find):
    with pytest.raises(api.NoSuchDevice):
        haptic_events.get_haptic_events("nope")


def test_get_haptic_events_device_without_haptics(find):
    find["K850"] = _device("K850", haptics=False)

    with pytest.raises(api.NotSupported):
        haptic_events.get_haptic_events("K850")


def test_get_haptic_events_offline_device_never_seen_online(find):
    find["B042-1"] = _device(online=False, haptics=False)

    with pytest.raises(api.DeviceOffline):
        haptic_events.get_haptic_events("B042-1")


def test_set_haptic_event_stores_in_the_persister(find, no_saves):
    device = find["B042-1"] = _device()

    result = haptic_events.set_haptic_event("B042-1", "desktop_switch", "SHARP STATE CHANGE")

    assert device.persister[haptic_events.PERSIST_KEY] == {"desktop_switch": "SHARP STATE CHANGE"}
    assert result["events"][1] == {
        "event": "desktop_switch",
        "label": "Virtual desktop switched",
        "waveform": "SHARP STATE CHANGE",
    }
    no_saves.assert_called_once_with(defer=True)  # the configuration is saved by the existing machinery


def test_set_haptic_event_empty_waveform_disables(find, no_saves):
    device = find["B042-1"] = _device(stored={"notification": "WAVE", "battery_low": "HAPPY ALERT"})

    result = haptic_events.set_haptic_event("B042-1", "notification", "")

    assert device.persister[haptic_events.PERSIST_KEY] == {"battery_low": "HAPPY ALERT"}
    assert [e["waveform"] for e in result["events"]] == [None, None, "HAPPY ALERT"]


@pytest.mark.parametrize("event, waveform", [("lid_closed", "WAVE"), ("notification", "BUZZ"), ("notification", "wave")])
def test_set_haptic_event_invalid_values(find, no_saves, event, waveform):
    device = find["B042-1"] = _device()

    with pytest.raises(api.InvalidValue):
        haptic_events.set_haptic_event("B042-1", event, waveform)

    assert haptic_events.PERSIST_KEY not in device.persister


def test_set_haptic_event_device_without_haptics(find, no_saves):
    find["K850"] = _device("K850", haptics=False)

    with pytest.raises(api.NotSupported):
        haptic_events.set_haptic_event("K850", "notification", "WAVE")


def test_set_haptic_event_without_persister(find):
    find["B042-1"] = _device(persister=False)

    with pytest.raises(api.ApiError):
        haptic_events.set_haptic_event("B042-1", "notification", "WAVE")


def test_mapping_is_saved_in_config_yaml(find, no_saves):
    device = find["B042-1"] = _device()
    haptic_events.set_haptic_event("B042-1", "notification", "WAVE")

    saved = yaml.safe_load(yaml.dump([device.persister]))

    assert saved == [{"_haptic_events": {"notification": "WAVE"}}]


def test_mapping_ignores_garbage():
    assert haptic_events.mapping(_device(stored="WAVE")) == {}
    assert haptic_events.mapping(_device(persister=False)) == {}


# --- playing ---


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def _player(devices, worker=None):
    played = []
    clock = FakeClock()
    player = haptic_events.HapticEvents(
        devices=lambda: devices,
        play=lambda dev_id, waveform: played.append((dev_id, waveform)),
        worker=worker or (lambda function, *args: function(*args)),
        clock=clock,
    )
    return player, played, clock


def test_fire_plays_on_online_devices_with_a_mapping():
    devices = [
        _device("mouse", stored={"notification": "WAVE", "desktop_switch": "SHARP STATE CHANGE"}),
        _device("offline-mouse", online=False, stored={"notification": "WAVE"}),
        _device("other-mouse", stored={"desktop_switch": "WAVE"}),
        _device("keyboard", haptics=False),
    ]
    player, played, _clock = _player(devices)

    player.fire("notification")

    assert played == [("mouse", "WAVE")]


def test_fire_is_rate_limited_per_device():
    devices = [_device("mouse", stored={"notification": "WAVE"}), _device("mouse2", stored={"desktop_switch": "WAVE"})]
    player, played, clock = _player(devices)

    player.fire("notification")
    clock.now += 0.1
    player.fire("notification")  # too soon for mouse
    player.fire("desktop_switch")  # but mouse2 has not played
    clock.now += haptic_events.MIN_INTERVAL
    player.fire("notification")

    assert played == [("mouse", "WAVE"), ("mouse2", "WAVE"), ("mouse", "WAVE")]


def test_fire_skips_a_device_whose_play_is_still_pending():
    queued = []
    player, played, clock = _player(
        [_device("mouse", stored={"notification": "WAVE"})], worker=lambda *task: queued.append(task)
    )

    player.fire("notification")
    clock.now += 10  # long after the rate limit, but the device has not answered yet
    player.fire("notification")
    assert len(queued) == 1

    function, *args = queued.pop()
    function(*args)
    player.fire("notification")
    assert len(queued) == 1


@pytest.mark.parametrize("error", [api.DeviceOffline("asleep"), RuntimeError("boom")])
def test_play_errors_are_logged_and_release_the_device(error, caplog):
    caplog.set_level(logging.INFO, logger="solaar.haptic_events")
    device = _device("mouse", stored={"notification": "WAVE"})
    clock = FakeClock()
    play = mock.Mock(side_effect=error)
    player = haptic_events.HapticEvents(
        devices=lambda: [device], play=play, worker=lambda function, *args: function(*args), clock=clock
    )

    player.fire("notification")
    clock.now += 1
    player.fire("notification")

    assert play.call_count == 2
    assert "cannot play WAVE" in caplog.text or "playing WAVE for notification failed" in caplog.text


def test_fire_survives_a_broken_device():
    broken = SimpleNamespace(id="broken", online=True)  # no persister attribute at all
    player, played, _clock = _player([broken, _device("mouse", stored={"notification": "WAVE"})])

    player.fire("notification")

    assert played == [("mouse", "WAVE")]


def test_default_player_uses_the_api(monkeypatch):
    play = mock.Mock()
    monkeypatch.setattr(api, "play_haptic", play)
    monkeypatch.setattr(api, "devices", lambda: [_device("mouse", stored={"notification": "WAVE"})])
    player = haptic_events.HapticEvents(worker=lambda function, *args: function(*args))

    player.fire("notification")

    play.assert_called_once_with("mouse", "WAVE")


def test_start_and_stop_run_the_worker():
    worker = mock.Mock()
    player = haptic_events.HapticEvents(worker=worker)

    player.start()
    player.stop()

    worker.start.assert_called_once()
    worker.stop.assert_called_once()


# --- battery_low ---


def _battery(level, status=BatteryStatus.DISCHARGING):
    return Battery(level, None, status, None)


def _battery_player():
    mouse = _device("mouse", stored={"battery_low": "HAPPY ALERT"})
    keyboard = _device("keyboard", haptics=False)
    player, played, clock = _player([mouse, keyboard])
    return player, played, clock, mouse, keyboard


def _levels(player, clock, device, *batteries):
    for battery in batteries:
        clock.now += 1
        device.battery_info = battery
        player.battery_changed(device)


def test_battery_low_fires_once_when_crossing_the_threshold():
    player, played, clock, mouse, _keyboard = _battery_player()

    _levels(player, clock, mouse, _battery(30), _battery(11), _battery(10), _battery(9), _battery(5))

    assert played == [("mouse", "HAPPY ALERT")]


def test_battery_low_rearms_only_above_the_rearm_level():
    player, played, clock, mouse, _keyboard = _battery_player()

    _levels(player, clock, mouse, _battery(10), _battery(14), _battery(9))
    assert len(played) == 1  # 14 % is within the hysteresis band

    _levels(player, clock, mouse, _battery(80, BatteryStatus.RECHARGING), _battery(80), _battery(8))
    assert len(played) == 2


def test_battery_low_from_another_device_plays_on_the_mapped_device():
    """A keyboard cannot buzz, but the mouse can tell about its low battery."""
    player, played, clock, _mouse, keyboard = _battery_player()

    _levels(player, clock, keyboard, _battery(BatteryLevelApproximation.CRITICAL))

    assert played == [("mouse", "HAPPY ALERT")]


def test_battery_low_fires_at_startup_when_already_low():
    player, played, clock, mouse, _keyboard = _battery_player()

    _levels(player, clock, mouse, _battery(7))

    assert played == [("mouse", "HAPPY ALERT")]


@pytest.mark.parametrize(
    "battery",
    [
        None,
        _battery(None),
        _battery(5, BatteryStatus.RECHARGING),
        _battery(5, BatteryStatus.SLOW_RECHARGE),
        _battery(5, BatteryStatus.OFFLINE),  # the last known level of a device that went away
        _battery(BatteryLevelApproximation.LOW),
    ],
)
def test_battery_low_does_not_fire(battery):
    player, played, clock, mouse, _keyboard = _battery_player()

    _levels(player, clock, mouse, battery)

    assert played == []


def test_battery_low_does_not_fire_while_charging_but_stays_armed():
    player, played, clock, mouse, _keyboard = _battery_player()

    _levels(player, clock, mouse, _battery(5, BatteryStatus.RECHARGING), _battery(6))

    assert played == [("mouse", "HAPPY ALERT")]  # unplugged while still low
