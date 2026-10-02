from unittest import mock

import pytest

from logitech_receiver.common import Alert
from solaar import daemon
from solaar.errors import ErrorReason


@pytest.fixture(autouse=True)
def service(monkeypatch):
    """Never touch the real session bus: replace the D-Bus service with a mock."""
    service_class = mock.Mock(name="Service")
    monkeypatch.setattr(daemon.dbus_service, "Service", service_class)
    return service_class.return_value


@pytest.fixture
def run_idle_now(monkeypatch):
    """Run GLib.idle_add callbacks immediately instead of on the main loop."""
    monkeypatch.setattr(daemon.GLib, "idle_add", lambda function, *args: function(*args))


@pytest.fixture
def show(monkeypatch):
    show = mock.Mock(name="show")
    monkeypatch.setattr(daemon.desktop_notifications, "show", show)
    return show


@pytest.mark.parametrize(
    "alert, notifications, shown",
    [
        (Alert.NOTIFICATION, True, True),
        (Alert.ATTENTION, True, True),
        (Alert.NONE, True, False),
        (None, True, False),
        (Alert.NOTIFICATION, False, False),
    ],
)
def test_status_changed_notifies_on_alerts(run_idle_now, show, alert, notifications, shown):
    device = mock.Mock(name="device")

    daemon.Daemon(notifications=notifications).status_changed(device, alert, "connected")

    assert show.called is shown
    if shown:
        show.assert_called_once_with(device, "connected")


def test_status_changed_ignores_missing_device(run_idle_now, show):
    daemon.Daemon().status_changed(None, Alert.NOTIFICATION, "gone")

    show.assert_not_called()


def _device_with_setting(name):
    setting = mock.Mock(name=name)
    setting.name = name
    return mock.Mock(settings=[setting]), setting


def test_setting_changed_records_value(run_idle_now):
    device, setting = _device_with_setting("dpi")
    setting_class = mock.Mock()
    setting_class.name = "dpi"

    daemon.Daemon().setting_changed(device, setting_class, [1600])

    setting.update.assert_called_once_with(1600)
    setting.update_key_value.assert_not_called()


def test_setting_changed_records_key_value(run_idle_now):
    device, setting = _device_with_setting("divert-keys")
    setting_class = mock.Mock()
    setting_class.name = "divert-keys"

    daemon.Daemon().setting_changed(device, setting_class, [0x1A0, 1])

    setting.update_key_value.assert_called_once_with(0x1A0, 1)


def test_setting_changed_unknown_setting_is_ignored(run_idle_now):
    device, setting = _device_with_setting("dpi")
    setting_class = mock.Mock()
    setting_class.name = "smart-shift"

    daemon.Daemon().setting_changed(device, setting_class, [10])

    setting.update.assert_not_called()


def test_permission_error_is_logged(run_idle_now, caplog):
    daemon.Daemon().error(ErrorReason.PERMISSIONS, "/dev/hidraw4")

    assert "no permission to open /dev/hidraw4" in caplog.text


@pytest.fixture
def lifecycle(monkeypatch):
    mocks = mock.Mock()
    monkeypatch.setattr(daemon.listener, "setup_scanner", mocks.setup_scanner)
    monkeypatch.setattr(daemon.listener, "start_all", mocks.start_all)
    monkeypatch.setattr(daemon.listener, "stop_all", mocks.stop_all)
    monkeypatch.setattr(daemon.dbus, "watch_suspend_resume", mocks.watch_suspend_resume)
    monkeypatch.setattr(daemon.desktop_notifications, "init", mocks.init)
    monkeypatch.setattr(daemon.desktop_notifications, "uninit", mocks.uninit)
    return mocks


def test_run_starts_listeners_and_stops_cleanly(lifecycle):
    d = daemon.Daemon()
    lifecycle.start_all.side_effect = d.quit  # quit as soon as the listeners are started

    assert d.run() == 0

    lifecycle.setup_scanner.assert_called_once_with(d.status_changed, d.setting_changed, d.error)
    lifecycle.watch_suspend_resume.assert_called_once()
    lifecycle.init.assert_called_once()
    lifecycle.stop_all.assert_called_once()
    lifecycle.uninit.assert_called_once()


def test_run_without_notifications(lifecycle):
    d = daemon.Daemon(notifications=False)
    lifecycle.start_all.side_effect = d.quit

    d.run()

    lifecycle.init.assert_not_called()


def test_run_exits_with_error_when_listeners_fail(lifecycle):
    lifecycle.start_all.side_effect = RuntimeError("boom")

    assert daemon.Daemon().run() == 1
    lifecycle.stop_all.assert_called_once()


def test_version_option(capsys):
    with pytest.raises(SystemExit) as exit_info:
        daemon.main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.startswith("plasmaard ")


def test_status_changed_forwards_devices_to_dbus(run_idle_now, show, service):
    device = mock.Mock(name="device", kind="mouse")

    daemon.Daemon().status_changed(device, Alert.NONE, None)

    service.device_changed.assert_called_once_with(device)


def test_status_changed_skips_receivers_for_dbus(run_idle_now, show, service):
    receiver = mock.Mock(name="receiver", kind=None)

    daemon.Daemon().status_changed(receiver, Alert.NONE, None)

    service.device_changed.assert_not_called()


def test_setting_changed_forwards_to_dbus(run_idle_now, service):
    device, setting = _device_with_setting("dpi")
    setting_class = mock.Mock()
    setting_class.name = "dpi"

    daemon.Daemon().setting_changed(device, setting_class, [800])

    service.setting_changed.assert_called_once_with(device, setting)


def test_run_starts_and_stops_dbus_service(lifecycle, service):
    d = daemon.Daemon()
    lifecycle.start_all.side_effect = d.quit

    d.run()

    service.start.assert_called_once()
    service.stop.assert_called_once()


def test_no_dbus_option(lifecycle, service):
    d = daemon.Daemon(dbus_api=False)
    lifecycle.start_all.side_effect = d.quit

    d.run()

    assert d.service is None
    service.start.assert_not_called()


def test_losing_bus_name_exits_with_error(lifecycle, service):
    d = daemon.Daemon()
    lifecycle.start_all.side_effect = d._name_lost

    assert d.run() == 1
