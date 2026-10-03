import json
import struct

from types import SimpleNamespace
from unittest import mock

import pytest
import yaml

from logitech_receiver import diversion
from logitech_receiver.base import HIDPPNotification
from logitech_receiver.common import NamedInt
from logitech_receiver.common import NamedInts
from logitech_receiver.hidpp20_constants import SupportedFeature
from logitech_receiver.settings import Kind
from solaar import api
from solaar import buttons

DEV_ID = "B04200000000-BD2BC136"
HAPTIC = NamedInt(0x1A0, "Haptic")
GESTURE = NamedInt(0xC3, "Mouse Gesture Button")
SHIFT = NamedInt(0xC4, "Smart Shift")
OVERVIEW = {"component": "kwin", "action": "Overview"}
GRID = {"component": "kwin", "action": "Grid View"}
DESKTOP = {"component": "kwin", "action": "Show Desktop"}
NO_GESTURES = {"up": None, "down": None, "left": None, "right": None, "click": None}


class FakeDivertKeys:
    """Behaves like the divert-keys setting: a cached per-key map, written key by key."""

    name = "divert-keys"
    kind = Kind.MAP_CHOICE
    persist = True

    def __init__(self, value=None, write_ok=True):
        self.choices = {
            HAPTIC: NamedInts(Regular=0, Diverted=1),
            GESTURE: NamedInts(**{"Regular": 0, "Diverted": 1, "Mouse Gestures": 2}),
            SHIFT: NamedInts(**{"Regular": 0, "Diverted": 1, "Mouse Gestures": 2, "Sliding DPI": 3}),
        }
        self.value = dict(value) if value is not None else {0x1A0: 0, 0xC3: 0, 0xC4: 0}
        self.write_ok = write_ok
        self.writes = []

    def read(self, cached=True):
        return self.value

    def write_key_value(self, key, value, save=True):
        self.writes.append((key, value))
        if not self.write_ok:
            return None
        self.value[int(key)] = value
        return value


def make_device(settings=(), online=True, model="B04200000000", unit="BD2BC136"):
    device = mock.Mock(name="device")
    device.name = device.codename = "MX Master 4"
    device.online = online
    device.modelId, device.unitId, device.serial = model, unit, ""
    device.number, device.path, device.receiver = 255, "/dev/hidraw4", None
    device.settings = list(settings)
    return device


@pytest.fixture
def registry(monkeypatch):
    """Expose devices through fake listener threads, like the running daemon does."""
    listeners = {}
    monkeypatch.setattr(api.listener, "_all_listeners", listeners)

    def add(device):
        device.isDevice = True
        listeners[f"/dev/hidraw{len(listeners)}"] = mock.Mock(receiver=device)
        return device

    return add


@pytest.fixture
def divert(registry):
    setting = FakeDivertKeys()
    registry(make_device([setting]))
    return setting


@pytest.fixture
def buttons_file(isolate_button_actions):
    return isolate_button_actions


def _set(control, **config):
    return buttons.set_button_action(DEV_ID, control, json.dumps(config))


def _generated():
    return [rule.data()["Rule"] for rule in diversion._generated_rules.components] if diversion._generated_rules else []


# --- GetButtonActions ---


def test_get_button_actions_lists_divertable_buttons(divert):
    divert.value[0xC3] = 2

    result = buttons.get_button_actions(DEV_ID)

    assert result["device_id"] == DEV_ID
    assert result["buttons"] == [
        {"control": 416, "name": "Haptic", "modes": ["off", "press"], "mode": "off", "press": None, "gestures": NO_GESTURES},
        {
            "control": 195,
            "name": "Mouse Gesture Button",
            "modes": ["off", "press", "gesture"],
            "mode": "gesture",
            "press": None,
            "gestures": NO_GESTURES,
        },
        {
            "control": 196,
            "name": "Smart Shift",
            "modes": ["off", "press", "gesture"],  # Sliding DPI is not exposed
            "mode": "off",
            "press": None,
            "gestures": NO_GESTURES,
        },
    ]
    json.loads(api.to_json(result))


def test_get_button_actions_reports_other_divert_values_as_off(divert):
    divert.value[0xC4] = 3  # Sliding DPI

    [*_, shift] = buttons.get_button_actions(DEV_ID)["buttons"]

    assert shift["mode"] == "off"


def test_get_button_actions_errors(registry):
    registry(make_device([], unit="AAAA"))

    with pytest.raises(api.NoSuchDevice):
        buttons.get_button_actions("nope")
    with pytest.raises(api.NotSupported):
        buttons.get_button_actions("B04200000000-AAAA")


# --- SetButtonAction ---


def test_set_press_action(divert, buttons_file):
    button, written = _set(416, mode="press", press=OVERVIEW)

    assert divert.writes == [(416, 1)]
    assert written is divert
    assert button == {
        "control": 416,
        "name": "Haptic",
        "modes": ["off", "press"],
        "mode": "press",
        "press": OVERVIEW,
        "gestures": NO_GESTURES,
    }
    assert yaml.safe_load(buttons_file.read_text()) == {
        DEV_ID: {416: {"name": "Haptic", "mode": "press", "press": ["kwin", "Overview"]}}
    }
    assert _generated() == [[{"Device": "BD2BC136"}, {"Key": ["Haptic", "pressed"]}, {"KdeShortcut": ["kwin", "Overview"]}]]
    assert buttons.get_button_actions(DEV_ID)["buttons"][0] == button


def test_set_gestures_merges_directions(divert, buttons_file):
    _set(195, mode="gesture", gestures={"up": GRID, "click": OVERVIEW})
    button, written = _set(195, gestures={"down": DESKTOP, "click": None})

    assert written is None  # no mode: divert-keys untouched
    assert divert.writes == [(195, 2)]
    assert button["mode"] == "gesture"
    assert button["gestures"] == {**NO_GESTURES, "up": GRID, "down": DESKTOP}
    assert _generated() == [
        [
            {"Device": "BD2BC136"},
            {"MouseGesture": ["Mouse Gesture Button", "Mouse Up"]},
            {"KdeShortcut": ["kwin", "Grid View"]},
        ],
        [
            {"Device": "BD2BC136"},
            {"MouseGesture": ["Mouse Gesture Button", "Mouse Down"]},
            {"KdeShortcut": ["kwin", "Show Desktop"]},
        ],
    ]
    text = buttons_file.read_text()
    assert text.startswith("# plasmaar button actions")
    assert "up: [kwin, Grid View]" in text  # actions stay one-liners for hand editing


def test_click_gesture_rule_has_no_movement(divert):
    _set(195, mode="gesture", gestures={"click": OVERVIEW})

    assert _generated() == [
        [{"Device": "BD2BC136"}, {"MouseGesture": ["Mouse Gesture Button"]}, {"KdeShortcut": ["kwin", "Overview"]}]
    ]


def test_off_keeps_actions_and_switching_back_restores_them(divert):
    _set(416, mode="press", press=OVERVIEW)

    button, _ = _set(416, mode="off")
    assert divert.writes[-1] == (416, 0)
    assert button["press"] == OVERVIEW
    assert diversion._generated_rules is None

    _set(416, mode="press")
    assert _generated()[0][2] == {"KdeShortcut": ["kwin", "Overview"]}


def test_clearing_everything_removes_the_entry(divert, buttons_file):
    _set(416, mode="press", press=OVERVIEW)

    _set(416, mode="off", press=None)

    assert buttons._mappings == {}
    assert yaml.safe_load(buttons_file.read_text()) is None  # only the header comment is left


def test_actions_without_mode_work_offline(registry):
    divert = FakeDivertKeys({0x1A0: 1, 0xC3: 0, 0xC4: 0})
    registry(make_device([divert], online=False))

    button, written = _set(416, press=OVERVIEW)

    assert written is None and divert.writes == []
    assert button["mode"] == "press"  # follows how the button is diverted
    assert _generated()[0][1] == {"Key": ["Haptic", "pressed"]}


def test_mode_needs_the_device_online(registry):
    divert = FakeDivertKeys()
    registry(make_device([divert], online=False))

    with pytest.raises(api.DeviceOffline):
        _set(416, mode="press", press=OVERVIEW)

    assert buttons._mappings == {}


@pytest.mark.parametrize(
    "control, config_json, error",
    [
        (416, '{"mode": "gesture"}', api.NotSupported),  # Haptic cannot do gestures
        (999, '{"mode": "press"}', api.InvalidValue),
        (416, '{"mode": "sliding"}', api.InvalidValue),
        (416, '{"mode": null}', api.InvalidValue),
        (416, '{"press": ["kwin", "Overview"]}', api.InvalidValue),  # the JSON form is an object
        (416, '{"press": {"component": "kwin"}}', api.InvalidValue),
        (416, '{"press": {"component": "kwin", "action": ""}}', api.InvalidValue),
        (195, '{"gestures": {"diagonal": null}}', api.InvalidValue),
        (195, '{"gestures": {"up": "Overview"}}', api.InvalidValue),
        (195, '{"gestures": []}', api.InvalidValue),
        (416, '{"mod": "press"}', api.InvalidValue),
        (416, '["press"]', api.InvalidValue),
        (416, "not json", api.InvalidValue),
    ],
)
def test_set_button_action_rejects_bad_input_before_writing(divert, control, config_json, error):
    with pytest.raises(error):
        buttons.set_button_action(DEV_ID, control, config_json)

    assert divert.writes == []
    assert buttons._mappings == {}


def test_set_button_action_without_divert_keys(registry):
    registry(make_device([]))

    with pytest.raises(api.NotSupported):
        _set(416, mode="press")


def test_failed_divert_write_stores_nothing(registry):
    registry(make_device([FakeDivertKeys(write_ok=False)]))

    with pytest.raises(api.ApiError):
        _set(416, mode="press", press=OVERVIEW)

    assert buttons._mappings == {}


def test_save_failure_keeps_the_mapping_for_the_session(divert, monkeypatch, tmp_path, caplog):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("")
    monkeypatch.setattr(buttons, "_file_path", str(blocker / "buttons.yaml"))

    button, _ = _set(416, mode="press", press=OVERVIEW)

    assert button["press"] == OVERVIEW
    assert _generated()
    assert "cannot save button actions" in caplog.text


# --- divert-keys changed elsewhere ---


def test_sync_modes_follows_divert_changes(divert, buttons_file):
    _set(416, mode="press", press=OVERVIEW)

    assert buttons.sync_modes(DEV_ID, {416: 0, 195: 2}) is True
    assert buttons._mappings[DEV_ID][416]["mode"] == "off"
    assert diversion._generated_rules is None
    assert yaml.safe_load(buttons_file.read_text())[DEV_ID][416]["mode"] == "off"

    assert buttons.sync_modes(DEV_ID, {"416": 1}) is True
    assert _generated()


def test_sync_modes_without_changes(divert):
    _set(416, mode="press", press=OVERVIEW)

    assert buttons.sync_modes(DEV_ID, {416: 1}) is False
    assert buttons.sync_modes("other", {416: 0}) is False
    assert buttons.sync_modes(DEV_ID, None) is False


# --- the file ---


def test_reload_reads_the_file(buttons_file):
    buttons_file.write_text(
        "B04200000000-BD2BC136:\n"
        "  416: {mode: press, press: [kwin, Overview]}\n"
        "  '195':\n"
        "    mode: gesture\n"
        "    gestures: {up: [kwin, Grid View], left: {component: kwin, action: Switch One Desktop to the Left}}\n"
    )

    assert buttons.reload() == {DEV_ID}

    assert buttons._mappings[DEV_ID][195]["gestures"]["left"] == {
        "component": "kwin",
        "action": "Switch One Desktop to the Left",
    }
    assert [rule[1] for rule in _generated()] == [
        {"MouseGesture": ["Mouse Gesture Button", "Mouse Up"]},
        {"MouseGesture": ["Mouse Gesture Button", "Mouse Left"]},
        {"Key": ["Haptic", "pressed"]},
    ]


def test_reload_after_own_write_changes_nothing(divert):
    _set(195, mode="gesture", gestures={"up": GRID, "click": OVERVIEW})
    _set(416, mode="press", press=OVERVIEW)
    rules = diversion.rules

    assert buttons.reload() == set()
    assert diversion.rules is rules


def test_reload_of_a_removed_file_drops_the_mappings(divert, buttons_file):
    _set(416, mode="press", press=OVERVIEW)
    buttons_file.unlink()

    assert buttons.reload() == {DEV_ID}
    assert buttons._mappings == {}
    assert diversion._generated_rules is None


def test_missing_file(buttons_file):
    assert buttons.reload() == set()
    assert buttons._mappings == {}


def test_unreadable_file_keeps_mappings_and_is_backed_up(divert, buttons_file, caplog):
    _set(416, mode="press", press=OVERVIEW)
    buttons_file.write_text("B04200000000-BD2BC136: [unclosed\n")

    assert buttons.reload() == set()
    assert buttons._mappings[DEV_ID][416]["press"] == OVERVIEW
    assert "cannot read button actions" in caplog.text

    _set(416, press=GRID)

    assert buttons_file.with_name("buttons.yaml.bak").read_text() == "B04200000000-BD2BC136: [unclosed\n"
    assert yaml.safe_load(buttons_file.read_text())[DEV_ID][416]["press"] == ["kwin", "Grid View"]


def test_invalid_entries_are_skipped(buttons_file, caplog):
    buttons_file.write_text(
        "B04200000000-BD2BC136:\n"
        "  416: {mode: off, press: [kwin, Overview]}\n"  # unquoted off is YAML false
        "  abc: {mode: press}\n"
        "  195: {mode: swipe, gestures: {up: [kwin], sideways: [kwin, Overview], down: [kwin, Show Desktop]}}\n"
        "  196: just text\n"
        "  82: {mode: off}\n"  # nothing configured
        "other: [1, 2]\n"
    )

    buttons.reload()

    assert buttons._mappings == {
        DEV_ID: {
            416: {"mode": "off", "press": OVERVIEW, "gestures": {}},
            195: {"mode": "off", "press": None, "gestures": {"down": DESKTOP}},
        }
    }
    assert "unknown mode 'swipe'" in caplog.text
    assert "ignoring gesture 'sideways'" in caplog.text


def test_file_that_is_not_a_mapping(buttons_file):
    buttons_file.write_text("- just\n- a list\n")

    assert buttons.reload() == set()


# --- the rules ---


def test_device_without_unit_id_is_matched_by_id():
    rule = buttons.generate_rules({"/dev/hidraw4#2": {416: {"mode": "press", "press": OVERVIEW, "gestures": {}}}})

    [condition, _key, _action] = rule.components[0].components
    paired = SimpleNamespace(modelId=None, unitId=None, receiver=SimpleNamespace(path="/dev/hidraw4"), number=2)
    other = SimpleNamespace(modelId=None, unitId=None, receiver=SimpleNamespace(path="/dev/hidraw4"), number=3)
    assert condition.evaluate(None, None, paired, None) is True
    assert condition.evaluate(None, None, other, None) is False
    assert condition.data() == {"Device": "/dev/hidraw4#2"}


def test_no_mappings_no_rules():
    assert buttons.generate_rules({}) is None
    assert buttons.generate_rules({DEV_ID: {416: {"mode": "press", "press": None, "gestures": {"up": GRID}}}}) is None


def _gesture(*values):
    return HIDPPNotification(0, 0, 0, 0, struct.pack("!" + len(values) * "h", *values))


@pytest.fixture
def user_rule(tmp_path, monkeypatch):
    """Hand-written rules.yaml rules, not scoped to a device: click → Expose, swipe down → Show Desktop."""
    path = tmp_path / "rules.yaml"
    path.write_text(
        "%YAML 1.3\n"
        "---\n- MouseGesture: Mouse Gesture Button\n- KdeShortcut: [kwin, Expose]\n...\n"
        "---\n- MouseGesture: Mouse Down\n- KdeShortcut: [kwin, Show Desktop]\n...\n"
    )
    monkeypatch.setattr(diversion, "_file_path", str(path))
    diversion.reload_config_rule_file()


def test_generated_rules_run_before_user_rules(divert, user_rule, monkeypatch):
    invoke = mock.Mock()
    monkeypatch.setattr(diversion, "invoke_kde_shortcut", invoke)
    mouse = SimpleNamespace(unitId="BD2BC136", serial="", codename="MX Master 4", name="MX Master 4")
    _set(195, mode="gesture", gestures={"click": OVERVIEW, "up": GRID})

    diversion.evaluate_rules(SupportedFeature.MOUSE_GESTURE, _gesture(195), mouse)  # click
    diversion.evaluate_rules(SupportedFeature.MOUSE_GESTURE, _gesture(195, 0, 0, -5, 0, 1, -8), mouse)  # paused swipe up

    assert invoke.call_args_list == [mock.call("kwin", "Overview"), mock.call("kwin", "Grid View")]


def test_unmapped_gestures_and_other_devices_reach_user_rules(divert, user_rule, monkeypatch):
    invoke = mock.Mock()
    monkeypatch.setattr(diversion, "invoke_kde_shortcut", invoke)
    mouse = SimpleNamespace(unitId="BD2BC136", serial="", codename="MX Master 4", name="MX Master 4")
    other = SimpleNamespace(unitId="3F51C045", serial="", codename="MX Anywhere 3S", name="MX Anywhere 3S")
    _set(195, mode="gesture", gestures={"click": OVERVIEW})

    diversion.evaluate_rules(SupportedFeature.MOUSE_GESTURE, _gesture(195, 0, 0, 5), mouse)  # down: not mapped
    diversion.evaluate_rules(SupportedFeature.MOUSE_GESTURE, _gesture(195), other)  # click on another mouse

    assert invoke.call_args_list == [mock.call("kwin", "Show Desktop"), mock.call("kwin", "Expose")]


def test_press_rule_runs_on_key_press(divert, monkeypatch):
    invoke = mock.Mock()
    monkeypatch.setattr(diversion, "invoke_kde_shortcut", invoke)
    mouse = SimpleNamespace(unitId="BD2BC136", serial="", codename="MX Master 4", name="MX Master 4")
    _set(416, mode="press", press=OVERVIEW)

    monkeypatch.setattr(diversion, "key_down", 0x1A0)
    diversion.evaluate_rules(SupportedFeature.REPROG_CONTROLS_V4, _gesture(0x1A0), mouse)
    monkeypatch.setattr(diversion, "key_down", None)
    diversion.evaluate_rules(SupportedFeature.REPROG_CONTROLS_V4, _gesture(0), mouse)  # the release

    invoke.assert_called_once_with("kwin", "Overview")
