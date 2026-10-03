import os

from pathlib import Path

import pytest

from solaar import i18n


def test_package_relative_location_is_the_source_share_dir():
    share = Path(__file__).resolve().parents[2] / "share"

    assert i18n._locale_locations()[-1] == str(share)


def test_finds_catalogues_in_a_location(tmp_path, monkeypatch):
    mo = tmp_path / "share" / "locale" / "fr" / "LC_MESSAGES" / "solaar.mo"
    mo.parent.mkdir(parents=True)
    mo.write_bytes(b"")
    monkeypatch.setattr(i18n, "_locale_locations", lambda: (str(tmp_path / "nothing"), str(tmp_path / "share")))

    assert i18n._find_locale_path("solaar") == os.path.join(str(tmp_path / "share"), "locale")


def test_no_catalogues_anywhere(tmp_path, monkeypatch):
    monkeypatch.setattr(i18n, "_locale_locations", lambda: (str(tmp_path),))

    with pytest.raises(FileNotFoundError):
        i18n._find_locale_path("solaar")
