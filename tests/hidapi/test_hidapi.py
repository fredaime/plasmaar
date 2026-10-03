# Modified for plasmaar since 2026-10-02 (https://github.com/fredaime/plasmaar); dated changes: its git history.
import errno
import platform

from unittest import mock

import pytest

if platform.system() == "Linux":
    import hidapi.udev_impl as hidapi
else:
    import hidapi.hidapi_impl as hidapi


def test_find_paired_node():
    hidapi.enumerate(mock.Mock())


@pytest.mark.skipif(platform.system() != "Linux", reason="udev implementation only")
def test_open_path_raises_permission_error_after_retries(monkeypatch):
    opener = mock.Mock(side_effect=PermissionError(errno.EACCES, "Permission denied"))
    monkeypatch.setattr(hidapi.os, "open", opener)
    monkeypatch.setattr(hidapi, "sleep", lambda _s: None)

    with pytest.raises(PermissionError):
        hidapi.open_path("/dev/hidraw4")

    assert opener.call_count == 3


@pytest.mark.skipif(platform.system() != "Linux", reason="udev implementation only")
def test_open_path_succeeds_after_transient_permission_error(monkeypatch):
    opener = mock.Mock(side_effect=[PermissionError(errno.EACCES, "Permission denied"), 42])
    monkeypatch.setattr(hidapi.os, "open", opener)
    monkeypatch.setattr(hidapi, "sleep", lambda _s: None)

    assert hidapi.open_path("/dev/hidraw4") == 42


@pytest.mark.skipif(platform.system() != "Linux", reason="udev implementation only")
def test_open_path_raises_other_errors_immediately(monkeypatch):
    opener = mock.Mock(side_effect=FileNotFoundError(errno.ENOENT, "No such device"))
    monkeypatch.setattr(hidapi.os, "open", opener)

    with pytest.raises(FileNotFoundError):
        hidapi.open_path("/dev/hidraw9")

    assert opener.call_count == 1
