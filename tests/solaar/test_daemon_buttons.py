"""plasmaard and the managed button actions file (buttons.yaml)."""

from unittest import mock

import pytest

from logitech_receiver import diversion
from solaar import buttons
from solaar import daemon

MAPPING = "B04200000000-BD2BC136:\n  416: {mode: press, press: [kwin, Overview]}\n"


@pytest.fixture(autouse=True)
def service(monkeypatch):
    """Never touch the real session bus: replace the D-Bus service with a mock."""
    service_class = mock.Mock(name="Service")
    monkeypatch.setattr(daemon.dbus_service, "Service", service_class)
    return service_class.return_value


@pytest.fixture
def lifecycle(monkeypatch):
    mocks = mock.Mock()
    for name in ("setup_scanner", "start_all", "stop_all"):
        monkeypatch.setattr(daemon.listener, name, getattr(mocks, name))
    monkeypatch.setattr(daemon.dbus, "watch_suspend_resume", mocks.watch_suspend_resume)
    monkeypatch.setattr(daemon.desktop_notifications, "init", mocks.init)
    monkeypatch.setattr(daemon.desktop_notifications, "uninit", mocks.uninit)
    return mocks


@pytest.fixture
def timeouts(monkeypatch):
    """Collect GLib.timeout_add callbacks instead of scheduling them."""
    scheduled = []
    monkeypatch.setattr(daemon.GLib, "timeout_add", lambda ms, fn: scheduled.append(fn) or len(scheduled))
    return scheduled


def test_run_loads_button_actions_and_watches_their_file(lifecycle, isolate_button_actions):
    isolate_button_actions.write_text(MAPPING)
    d = daemon.Daemon()
    lifecycle.start_all.side_effect = d.quit

    d.run()

    assert buttons._mappings["B04200000000-BD2BC136"][416]["press"] == {"component": "kwin", "action": "Overview"}
    assert diversion._generated_rules is not None
    assert d._buttons_monitor is not None
    assert d._buttons_monitor.is_cancelled()  # stopped with the daemon


def test_buttons_file_edit_reloads_once_and_signals(service, isolate_button_actions, timeouts):
    d = daemon.Daemon()
    isolate_button_actions.write_text(MAPPING)

    for event in (
        daemon.Gio.FileMonitorEvent.CHANGED,  # ignored: wait for the end of the save
        daemon.Gio.FileMonitorEvent.CHANGES_DONE_HINT,
        daemon.Gio.FileMonitorEvent.RENAMED,  # same save, already scheduled
    ):
        d._buttons_file_changed(None, None, None, event)

    assert len(timeouts) == 1
    timeouts[0]()
    service.button_actions_changed.assert_called_once_with("B04200000000-BD2BC136")
    assert d._buttons_reload_id is None
    assert diversion._generated_rules is not None


def test_own_write_reloads_without_signal(service, isolate_button_actions, timeouts):
    isolate_button_actions.write_text(MAPPING)
    buttons.reload()
    d = daemon.Daemon()

    d._buttons_file_changed(None, None, None, daemon.Gio.FileMonitorEvent.CHANGES_DONE_HINT)
    timeouts[0]()

    service.button_actions_changed.assert_not_called()


def test_buttons_reload_without_dbus(isolate_button_actions, timeouts):
    isolate_button_actions.write_text(MAPPING)
    d = daemon.Daemon(dbus_api=False)

    d._buttons_file_changed(None, None, None, daemon.Gio.FileMonitorEvent.CREATED)
    timeouts[0]()

    assert diversion._generated_rules is not None


def test_rules_file_reload_keeps_button_rules(isolate_button_actions, tmp_path, monkeypatch):
    isolate_button_actions.write_text(MAPPING)
    buttons.reload()
    generated = diversion._generated_rules
    rules_file = tmp_path / "rules.yaml"
    rules_file.write_text("%YAML 1.3\n---\n- MouseGesture: Mouse Up\n- KdeShortcut: [kwin, Grid View]\n...\n")
    monkeypatch.setattr(diversion, "_file_path", str(rules_file))

    daemon.Daemon()._reload_rules()

    assert diversion.rules.components[0] is generated
    assert diversion.rules.components[1].source == str(rules_file)
