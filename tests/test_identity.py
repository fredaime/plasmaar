"""plasmaar keeps its runtime state apart from an installed Solaar."""

import importlib
import os

import pytest
import solaar


def test_identity_constants():
    assert solaar.APP_NAME == "plasmaar"
    assert solaar.APP_ID == "io.github.fredaime.plasmaar"


@pytest.mark.parametrize(
    "module, attribute, filename",
    [
        ("solaar.configuration", "_yaml_file_path", "config.yaml"),
        ("solaar.configuration", "_json_file_path", "config.json"),
        ("logitech_receiver.diversion", "_file_path", "rules.yaml"),
        ("logitech_receiver.special_keys", "_keys_file_path", "keys.yaml"),
    ],
)
def test_state_files_live_in_plasmaar_config_dir(monkeypatch, tmp_path, module, attribute, filename):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    mod = importlib.reload(importlib.import_module(module))
    try:
        assert getattr(mod, attribute) == os.path.join(str(tmp_path), "plasmaar", filename)
    finally:
        monkeypatch.undo()
        importlib.reload(mod)


def test_notifications_use_plasmaar_identity():
    from logitech_receiver import desktop_notifications

    assert desktop_notifications.APP_NAME == "plasmaar"
    assert desktop_notifications.DESKTOP_ENTRY == "io.github.fredaime.plasmaar"


def test_desktop_entry_file_matches_the_notification_hint():
    from pathlib import Path

    from logitech_receiver import desktop_notifications

    entry = Path(__file__).resolve().parents[1] / "share" / "applications" / f"{desktop_notifications.DESKTOP_ENTRY}.desktop"
    text = entry.read_text()
    assert "Name=plasmaar" in text
    assert "X-GNOME-UsesNotifications=true" in text
