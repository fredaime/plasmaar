import struct
import textwrap

from unittest import mock
from unittest.mock import mock_open

import pytest

from logitech_receiver import diversion
from logitech_receiver.base import HIDPPNotification
from logitech_receiver.hidpp20_constants import SupportedFeature


@pytest.fixture
def rule_config():
    rule_content = """
    %YAML 1.3
    ---
    - MouseGesture: Mouse Left
    - KeyPress:
      - [Control_L, Alt_L, Left]
      - click
    ...
    ---
    - MouseGesture: Mouse Up
    - KeyPress:
      - [Super_L, Up]
      - click
    ...
    ---
    - Test: [thumb_wheel_up, 10]
    - KeyPress:
      - [Control_L, Page_Down]
      - click
    ...
    ---
    """
    return textwrap.dedent(rule_content)


def test_load_rule_config(rule_config):
    expected_rules = [
        [
            diversion.MouseGesture,
            diversion.KeyPress,
        ],
        [diversion.MouseGesture, diversion.KeyPress],
        [diversion.Test, diversion.KeyPress],
    ]

    with mock.patch("builtins.open", new=mock_open(read_data=rule_config)):
        loaded_rules = diversion._load_rule_config(file_path=mock.Mock())

    assert len(loaded_rules.components) == 2  # predefined and user configured rules
    user_configured_rules = loaded_rules.components[0]
    assert isinstance(user_configured_rules, diversion.Rule)

    for components, expected_components in zip(user_configured_rules.components, expected_rules):
        for component, expected_component in zip(components.components, expected_components):
            assert isinstance(component, expected_component)


def test_diversion_rule():
    args = [
        {
            "Rule": [  # Implement problematic keys for Craft and MX Master
                {"Rule": [{"Key": ["Brightness Down", "pressed"]}, {"KeyPress": "XF86_MonBrightnessDown"}]},
                {"Rule": [{"Key": ["Brightness Up", "pressed"]}, {"KeyPress": "XF86_MonBrightnessUp"}]},
            ]
        },
    ]

    rule = diversion.Rule(args)

    assert len(rule.components) == 1
    root_rule = rule.components[0]
    assert isinstance(root_rule, diversion.Rule)

    assert len(root_rule.components) == 2
    for component in root_rule.components:
        assert isinstance(component, diversion.Rule)
        assert len(component.components) == 2

        key = component.components[0]
        assert isinstance(key, diversion.Key)
        key = component.components[1]
        assert isinstance(key, diversion.KeyPress)


def test_key_is_down():
    result = diversion.key_is_down(key=diversion.CONTROL.G2)

    assert result is False


def test_feature():
    expected_data = {"Feature": "CONFIG CHANGE"}

    result = diversion.Feature("CONFIG_CHANGE")

    assert result.data() == expected_data


@pytest.mark.parametrize(
    "feature, data",
    [
        (
            SupportedFeature.REPROG_CONTROLS_V4,
            [0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08],
        ),
        (SupportedFeature.GKEY, [0x01, 0x02, 0x03, 0x04]),
        (SupportedFeature.MKEYS, [0x01, 0x02, 0x03, 0x04]),
        (SupportedFeature.MR, [0x01, 0x02, 0x03, 0x04]),
        (SupportedFeature.THUMB_WHEEL, [0x01, 0x02, 0x03, 0x04, 0x05]),
        (SupportedFeature.DEVICE_UNIT_ID, [0x01, 0x02, 0x03, 0x04, 0x05]),
    ],
)
def test_process_notification(feature, data):
    device_mock = mock.Mock()
    notification = HIDPPNotification(
        report_id=0x01,
        devnumber=1,
        sub_id=0x13,
        address=0x00,
        data=bytes(data),
    )

    diversion.process_notification(device_mock, notification, feature)


def _gesture_notification(*values):
    return HIDPPNotification(0, 0, 0, 0, struct.pack("!" + len(values) * "h", *values))


# recorded from an MX Master 4: gesture button (195), an upward swipe with a pause in the middle
_SWIPE_UP_WITH_PAUSE = (195, 0, 0, -5, 0, 1, -8)


@pytest.mark.parametrize(
    "movements, data, expected",
    [
        (["Mouse Up"], _SWIPE_UP_WITH_PAUSE, True),  # pause-split repeats count as one step
        (["Mouse Up"], (195, 0, 0, -5), True),
        (["Mouse Up", "Mouse Up"], _SWIPE_UP_WITH_PAUSE, True),  # exact multi-step rules still match
        (["Mouse Down"], _SWIPE_UP_WITH_PAUSE, False),
        (["Mouse Up", "Mouse Right"], (195, 0, 0, -5, 0, 1, -8, 0, 6, 0), True),
        (["Mouse Up", "Mouse Right"], (195, 0, 0, -5, 0, 6, 0, 0, 7, 1), True),
        (["Mouse Up"], (195, 0, 0, -5, 0, 6, 0), False),  # up then right is not just up
        (["Mouse Gesture Button", "Mouse Up"], _SWIPE_UP_WITH_PAUSE, True),
        (["Smart Shift", "Mouse Up"], _SWIPE_UP_WITH_PAUSE, False),
        ([], (195,), True),  # click without movement
        (["Mouse Up"], (195, 0, 0), False),  # malformed
    ],
)
def test_mouse_gesture_matching(movements, data, expected):
    condition = diversion.MouseGesture(movements, warn=False)

    result = condition.evaluate(diversion.SupportedFeature.MOUSE_GESTURE, _gesture_notification(*data), None, None)

    assert result is expected
