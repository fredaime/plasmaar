"""solaar.kde_actions against a fake connection (the private-bus test is in test_dbus_service.py)."""

import pytest

from gi.repository import GLib
from solaar import api
from solaar import kde_actions


def _info(action, label, component, component_label, context="default"):
    return (action, label, component, component_label, context, "Default Context", [], [])


class FakeConnection:
    """Answers call_sync like kglobalaccel; `components` maps an object path to (properties, shortcut infos)."""

    def __init__(self, components, broken=()):
        self.components = components
        self.broken = set(broken)
        self.calls = []

    def call_sync(self, bus_name, path, interface, method, parameters, reply_type, flags, timeout, cancellable):
        assert bus_name == "org.kde.kglobalaccel"
        self.calls.append((path, interface, method))
        if path in self.broken:
            raise GLib.Error("org.freedesktop.DBus.Error.UnknownObject")
        if method == "allComponents":
            return GLib.Variant("(ao)", (list(self.components),))
        properties, infos = self.components[path]
        if method == "GetAll":
            if properties is None:
                raise GLib.Error("org.freedesktop.DBus.Error.UnknownInterface")
            assert parameters.unpack() == ("org.kde.kglobalaccel.Component",)
            return GLib.Variant("(a{sv})", ({k: GLib.Variant("s", v) for k, v in properties.items()},))
        assert method == "allShortcutInfos" and parameters is None  # the default context
        return GLib.Variant("(a(ssssssaiai))", (infos,))


def test_lists_components_and_actions_sorted_by_label():
    connection = FakeConnection(
        {
            "/component/kwin": (
                {"uniqueName": "kwin", "friendlyName": "KWin"},
                [
                    _info("Overview", "Basculer vers l'aperçu", "kwin", "KWin"),
                    _info("Show Desktop", "Coup d'œil sur le bureau", "kwin", "KWin"),
                    _info("Grid View", "Basculer vers l'affichage en grille", "kwin", "KWin"),
                ],
            ),
            "/component/org_kde_spectacle_desktop": (
                {"uniqueName": "org.kde.spectacle.desktop", "friendlyName": "Spectacle"},
                [_info("RectangularRegionScreenShot", "Capturer une région", "org.kde.spectacle.desktop", "Spectacle")],
            ),
            "/component/kaccess": (
                {"uniqueName": "kaccess", "friendlyName": "Accessibilité"},
                [_info("Toggle Screen Reader On and Off", "Activer le lecteur d'écran", "kaccess", "Accessibilité")],
            ),
        }
    )

    listed = kde_actions.list_actions(connection)

    assert [c["component"] for c in listed] == ["kaccess", "kwin", "org.kde.spectacle.desktop"]  # by label, accents ignored
    assert listed[1] == {
        "component": "kwin",
        "label": "KWin",
        "actions": [
            {"name": "Grid View", "label": "Basculer vers l'affichage en grille"},
            {"name": "Overview", "label": "Basculer vers l'aperçu"},
            {"name": "Show Desktop", "label": "Coup d'œil sur le bureau"},
        ],
    }


def test_skips_empty_hidden_and_other_context_actions_and_dedupes():
    connection = FakeConnection(
        {
            "/component/kwin": (
                {"uniqueName": "kwin", "friendlyName": "KWin"},
                [
                    _info("Overview", "Aperçu", "kwin", "KWin"),
                    _info("Overview", "Aperçu (again)", "kwin", "KWin"),
                    _info("", "No name", "kwin", "KWin"),
                    _info("_k_friendly_name", "KWin", "kwin", "KWin"),
                    _info("Other", "Other context", "kwin", "KWin", context="special"),
                    _info("Unlabeled", "", "kwin", "KWin"),
                ],
            ),
            "/component/kwin_again": (
                {"uniqueName": "kwin", "friendlyName": "KWin"},
                [_info("Expose", "Exposé", "kwin", "KWin")],
            ),
            "/component/empty": ({"uniqueName": "empty", "friendlyName": "Nothing"}, []),
        }
    )

    [kwin] = kde_actions.list_actions(connection)

    assert kwin["actions"] == [
        {"name": "Overview", "label": "Aperçu"},
        {"name": "Expose", "label": "Exposé"},
        {"name": "Unlabeled", "label": "Unlabeled"},
    ]


def test_falls_back_to_the_shortcut_infos_for_names():
    connection = FakeConnection(
        {
            "/component/mediacontrol": (
                None,
                [_info("playpausemedia", "Lecture / Pause", "mediacontrol", "Contrôleur de média")],
            ),
            "/component/nameless": ({}, [_info("act", "Act", "", "")]),
        }
    )

    listed = kde_actions.list_actions(connection)

    assert [(c["component"], c["label"]) for c in listed] == [("mediacontrol", "Contrôleur de média")]


def test_a_broken_component_is_skipped(caplog):
    connection = FakeConnection(
        {
            "/component/gone": ({}, []),
            "/component/kwin": ({"uniqueName": "kwin", "friendlyName": "KWin"}, [_info("Overview", "Aperçu", "kwin", "KWin")]),
        },
        broken={"/component/gone"},
    )

    listed = kde_actions.list_actions(connection)

    assert [c["component"] for c in listed] == ["kwin"]
    assert "cannot list the KDE actions of /component/gone" in caplog.text


def test_no_kglobalaccel_is_an_api_error():
    connection = FakeConnection({}, broken={"/kglobalaccel"})

    with pytest.raises(api.ApiError, match="kglobalaccel"):
        kde_actions.list_actions(connection)


def test_no_connection_is_an_api_error():
    with pytest.raises(api.ApiError):
        kde_actions.list_actions(None)
