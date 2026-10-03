from unittest import mock

import pytest

from logitech_receiver import diversion


@pytest.mark.parametrize(
    "args, expected",
    [
        (["notify-send", "hello"], ["notify-send", "hello"]),
        ("xdotool", ["xdotool"]),
        ([], []),
    ],
)
def test_valid_arguments(args, expected, caplog):
    action = diversion.Execute(args)

    assert action.args == expected
    assert action.data() == {"Execute": expected}
    assert "Execute argument" not in caplog.text


@pytest.mark.parametrize("args", [None, 42, {"cmd": "ls"}, ["ls", 3], [["ls"]], ("ls", "-l")])
def test_invalid_arguments_warn_and_give_an_empty_command(args, caplog):
    action = diversion.Execute(args)

    assert action.args == []
    assert action.data() == {"Execute": []}
    assert str(action) == "Execute: "
    assert "rule Execute argument not list of strings" in caplog.text


def test_invalid_arguments_without_warning(caplog):
    diversion.Execute(42, warn=False)

    assert "Execute argument" not in caplog.text


def test_evaluate_runs_the_command(monkeypatch):
    popen = mock.Mock()
    monkeypatch.setattr(diversion.subprocess, "Popen", popen)

    diversion.Execute(["notify-send", "hello"]).evaluate(None, None, None, None)

    popen.assert_called_once_with(["notify-send", "hello"])


@pytest.mark.parametrize("args", [[], ["ls", 3], None])
def test_evaluate_empty_command_is_a_no_op(args, monkeypatch):
    popen = mock.Mock()
    monkeypatch.setattr(diversion.subprocess, "Popen", popen)

    result = diversion.Execute(args, warn=False).evaluate(None, None, None, None)

    assert result is None
    popen.assert_not_called()


def test_rule_from_yaml_data():
    rule = diversion.Rule([{"Key": ["Haptic", "pressed"]}, {"Execute": ["notify-send", "hi"]}])

    assert isinstance(rule.components[1], diversion.Execute)
    assert rule.data() == {"Rule": [{"Key": ["Haptic", "pressed"]}, {"Execute": ["notify-send", "hi"]}]}
