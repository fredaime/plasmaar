from unittest import mock

import pytest

from gi.repository import GLib
from logitech_receiver import diversion


def test_parse_and_data():
    action = diversion.KdeShortcut(["kwin", "Overview"])

    assert (action.component, action.shortcut) == ("kwin", "Overview")
    assert action.data() == {"KdeShortcut": ["kwin", "Overview"]}
    assert str(action) == "KdeShortcut: kwin Overview"


@pytest.mark.parametrize("args", ["Overview", ["kwin"], ["kwin", ""], ["kwin", 3], None])
def test_invalid_arguments_do_nothing(args, monkeypatch):
    invoke = mock.Mock()
    monkeypatch.setattr(diversion, "invoke_kde_shortcut", invoke)

    action = diversion.KdeShortcut(args, warn=False)
    action.evaluate(None, None, None, None)

    invoke.assert_not_called()


def test_evaluate_invokes_the_shortcut(monkeypatch):
    invoke = mock.Mock()
    monkeypatch.setattr(diversion, "invoke_kde_shortcut", invoke)

    diversion.KdeShortcut(["kwin", "Show Desktop"]).evaluate(None, None, None, None)

    invoke.assert_called_once_with("kwin", "Show Desktop")


def test_rule_from_yaml_data():
    rule = diversion.Rule([{"Key": ["Haptic", "pressed"]}, {"KdeShortcut": ["kwin", "Overview"]}])

    assert isinstance(rule.components[1], diversion.KdeShortcut)
    assert rule.data() == {"Rule": [{"Key": ["Haptic", "pressed"]}, {"KdeShortcut": ["kwin", "Overview"]}]}


@pytest.mark.parametrize(
    "component, path",
    [
        ("kwin", "/component/kwin"),
        ("org.kde.spectacle.desktop", "/component/org_kde_spectacle_desktop"),
        ("KDE Keyboard-Layout", "/component/KDE_Keyboard_Layout"),
    ],
)
def test_component_path(component, path):
    assert diversion.kde_component_path(component) == path


def test_invoke_calls_kglobalaccel(monkeypatch):
    bus = mock.Mock(name="session bus")
    monkeypatch.setattr(diversion, "_session_bus", bus)

    diversion.invoke_kde_shortcut("org.kde.spectacle.desktop", "RectangularRegionScreenShot")

    dest, path, interface, method, params, *_ = bus.call.call_args.args
    assert (dest, path, interface, method) == (
        "org.kde.kglobalaccel",
        "/component/org_kde_spectacle_desktop",
        "org.kde.kglobalaccel.Component",
        "invokeShortcut",
    )
    assert params.unpack() == ("RectangularRegionScreenShot",)


def test_invoke_failure_is_logged_not_raised(monkeypatch, caplog):
    bus = mock.Mock(name="session bus")
    bus.call.side_effect = GLib.Error("no session bus")
    monkeypatch.setattr(diversion, "_session_bus", bus)

    diversion.invoke_kde_shortcut("kwin", "Overview")

    assert "cannot invoke KDE shortcut kwin/Overview" in caplog.text


@pytest.fixture
def rules_file(tmp_path, monkeypatch):
    path = tmp_path / "rules.yaml"
    monkeypatch.setattr(diversion, "_file_path", str(path))
    monkeypatch.setattr(diversion, "rules", diversion.built_in_rules)
    return path


def test_reload_loads_user_rules(rules_file):
    rules_file.write_text("%YAML 1.3\n---\n- Key: [Haptic, pressed]\n- KdeShortcut: [kwin, Overview]\n...\n")

    diversion.reload_config_rule_file()

    user_rules = diversion.rules.components[0].components
    assert user_rules[0].data() == {"Rule": [{"Key": ["Haptic", "pressed"]}, {"KdeShortcut": ["kwin", "Overview"]}]}


def test_reload_after_removal_uses_built_in_rules(rules_file):
    rules_file.write_text("%YAML 1.3\n---\n- KdeShortcut: [kwin, Overview]\n...\n")
    diversion.reload_config_rule_file()
    rules_file.unlink()

    diversion.reload_config_rule_file()

    assert diversion.rules is diversion.built_in_rules
