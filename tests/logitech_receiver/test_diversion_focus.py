"""The Process condition with the active window reported by KWin (Plasma Wayland)."""

from types import SimpleNamespace
from unittest import mock

import pytest

from logitech_receiver import diversion


@pytest.fixture(autouse=True)
def fresh_focus(monkeypatch):
    monkeypatch.setattr(diversion, "_kwin_focus", None)
    monkeypatch.setattr(diversion, "_kwin_focus_missing_warned", False)


@pytest.fixture
def plasma_wayland(monkeypatch):
    monkeypatch.setattr(diversion, "wayland", "wayland-0")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    gnome = mock.Mock(name="gnome_dbus_interface_setup", return_value=False)
    monkeypatch.setattr(diversion, "gnome_dbus_interface_setup", gnome)
    return gnome


@pytest.fixture
def gnome_wayland(monkeypatch):
    monkeypatch.setattr(diversion, "wayland", "wayland-0")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    focus = mock.Mock(name="gnome_dbus_focus_prog", return_value=("org.gnome.Nautilus",))
    monkeypatch.setattr(diversion, "gnome_dbus_focus_prog", focus)
    monkeypatch.setattr(diversion, "gnome_dbus_interface_setup", mock.Mock(return_value=True))
    return focus


@pytest.fixture
def process_names(monkeypatch):
    names = {4242: "firefox-bin"}

    def process(pid):
        if pid not in names:
            raise ProcessLookupError(pid)
        return SimpleNamespace(name=lambda: names[pid])

    monkeypatch.setattr(diversion.psutil, "Process", process)
    return names


def _evaluate(process):
    return diversion.Process(process, warn=False).evaluate(None, None, None, None)


def test_set_kwin_focus_resolves_the_process_name(process_names):
    diversion.set_kwin_focus("org.mozilla.firefox", "firefox", 4242)

    assert diversion.kwin_focus_prog() == ("org.mozilla.firefox", "firefox", "firefox-bin")


def test_set_kwin_focus_with_a_vanished_process(process_names):
    diversion.set_kwin_focus("org.kde.konsole", "konsole", 999)

    assert diversion.kwin_focus_prog() == ("org.kde.konsole", "konsole", "")


def test_set_kwin_focus_without_active_window():
    diversion.set_kwin_focus("", "", 0)

    assert diversion.kwin_focus_prog() == ()


@pytest.mark.parametrize(
    "process, matches",
    [
        ("org.mozilla", True),  # resource class
        ("firefox", True),  # resource name
        ("firefox-bin", True),  # process name
        ("fire", True),  # startswith, as on X11
        ("mozilla", False),  # not a prefix of any
        ("org.kde.konsole", False),
    ],
)
def test_process_matches_the_kwin_focus_like_x11(plasma_wayland, process_names, process, matches):
    diversion.set_kwin_focus("org.mozilla.firefox", "firefox", 4242)

    assert _evaluate(process) is matches


def test_process_without_active_window_does_not_match(plasma_wayland):
    diversion.set_kwin_focus("", "", 0)

    assert not _evaluate("firefox")


def test_process_on_plasma_without_kwin_report_warns_once(plasma_wayland, caplog):
    assert _evaluate("firefox") is None
    assert _evaluate("firefox") is None

    assert caplog.text.count("plasmaar-focus") == 1
    plasma_wayland.assert_not_called()  # no GNOME Shell under KWin


def test_process_on_gnome_wayland_uses_the_extension(gnome_wayland):
    assert _evaluate("org.gnome.Nautilus") is True
    gnome_wayland.assert_called_once()


def test_kwin_focus_wins_over_the_gnome_extension(gnome_wayland):
    diversion.set_kwin_focus("org.kde.dolphin", "dolphin", 0)

    assert _evaluate("org.kde.dolphin") is True
    gnome_wayland.assert_not_called()


def test_process_on_x11_is_unchanged(monkeypatch):
    monkeypatch.setattr(diversion, "wayland", None)
    monkeypatch.setattr(diversion, "x11_setup", lambda: True)
    monkeypatch.setattr(diversion, "x11_focus_prog", lambda: ("Navigator", "firefox", "firefox-bin"))
    diversion.set_kwin_focus("org.kde.konsole", "konsole", 0)  # ignored on X11

    assert _evaluate("Navigator") is True
    assert _evaluate("org.kde.konsole") is False


def test_no_construction_warning_on_plasma(plasma_wayland, caplog):
    diversion.Process("firefox")

    assert "rules can only access the active process" not in caplog.text


def test_construction_warning_without_any_focus_source(monkeypatch, caplog):
    monkeypatch.setattr(diversion, "wayland", "wayland-0")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "sway")
    monkeypatch.setattr(diversion, "gnome_dbus_interface_setup", lambda: False)

    diversion.Process("firefox")

    assert "plasmaar-focus KWin script" in caplog.text
