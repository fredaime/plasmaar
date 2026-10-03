# Modified for plasmaar since 2026-10-02 (https://github.com/fredaime/plasmaar); dated changes: its git history.
import importlib
import os

from unittest import mock

import pytest

# Tests compare English strings, so never translate them: with compiled catalogues in share/locale
# (make compile_translations) and a non-English locale, solaar.i18n would otherwise pick them up.
# Set before any test module imports solaar (pytest loads this conftest first).
os.environ["LANGUAGE"] = "C"


@pytest.fixture(autouse=True)
def isolate_solaar_configuration(tmp_path, monkeypatch):
    """Redirect solaar.configuration at a throwaway path for every test.

    Tests build FakeDevices named 'TestDevice'; any that touch device.settings
    or device.persister without mocking call the real configuration.persister(),
    which loads and rewrites ~/.config/solaar/config.yaml — appending a fresh
    un-matchable TestDevice entry on every run. Pointing the paths at tmp_path
    and clearing the cached _config keeps each test off the real config and
    isolated from every other test."""
    from solaar import configuration

    monkeypatch.setattr(configuration, "_yaml_file_path", str(tmp_path / "config.yaml"))
    monkeypatch.setattr(configuration, "_json_file_path", str(tmp_path / "config.json"))
    monkeypatch.setattr(configuration, "_config", [])


@pytest.fixture(autouse=True)
def mock_desktop_notifications(monkeypatch):
    """Swap the libnotify backend for a mock in the GTK UI's desktop_notifications
    module. Tests still exercise the real init/alert/show code paths, but
    Notification.show() never reaches the daemon — without this the suite
    raises real 'MockDevice' / 'unknown' notifications on every run.

    Returns the Notify mock so notification tests can assert against it."""
    notify = mock.MagicMock(name="Notify")
    notify.is_initted.return_value = True
    notify.init.return_value = True
    try:
        module = importlib.import_module("solaar.ui.desktop_notifications")
    except Exception:
        return notify
    monkeypatch.setattr(module, "Notify", notify, raising=False)
    monkeypatch.setattr(module, "_notifications", {}, raising=False)
    return notify


@pytest.fixture(autouse=True)
def mock_notification_bus(monkeypatch):
    """Swap the core desktop_notifications D-Bus proxy for a mock, so no test
    reaches the real org.freedesktop.Notifications service.

    Returns the proxy mock; its call_sync replies with notification id 7."""
    from gi.repository import GLib
    from logitech_receiver import desktop_notifications

    proxy = mock.MagicMock(name="NotificationsProxy")
    proxy.call_sync.return_value = GLib.Variant("(u)", (7,))
    monkeypatch.setattr(desktop_notifications, "_proxy", proxy)
    monkeypatch.setattr(desktop_notifications, "_notifications", {})
    return proxy


@pytest.fixture(autouse=True)
def isolate_button_actions(tmp_path, monkeypatch):
    """Point solaar.buttons at a throwaway buttons.yaml, start with no mappings and no captured defaults,
    and restore the diversion rules afterwards, so no test reads the user's file or leaks generated rules.

    Returns the path of the test's buttons.yaml (not created)."""
    from logitech_receiver import diversion
    from solaar import api
    from solaar import buttons

    path = tmp_path / "buttons.yaml"
    monkeypatch.setattr(buttons, "_file_path", str(path))
    monkeypatch.setattr(buttons, "_mappings", {})
    monkeypatch.setattr(buttons, "_unreadable", False)
    monkeypatch.setattr(api, "_defaults_captured", set())
    for name in ("rules", "_generated_rules", "_loaded_rules"):
        monkeypatch.setattr(diversion, name, getattr(diversion, name))
    return path
