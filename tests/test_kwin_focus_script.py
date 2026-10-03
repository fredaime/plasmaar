"""The plasmaar-focus KWin script, run under node with a stand-in for KWin's scripting globals."""

import json
import shutil
import subprocess

from pathlib import Path

import pytest

from solaar import dbus_service

PACKAGE = Path(__file__).parent.parent / "share" / "kwin" / "scripts" / "plasmaar-focus"
MAIN_SCRIPT = PACKAGE / "contents" / "code" / "main.js"

# KWin 6: workspace.activeWindow, workspace.windowActivated (window or null); callDBus(service, path,
# interface, method, ...args). The harness records the calls and replays activations.
_HARNESS = """
const fs = require("fs");
const calls = [];
let activated = null;
globalThis.callDBus = (...args) => calls.push(args);
globalThis.workspace = {
    activeWindow: {resourceClass: "org.kde.konsole", resourceName: "konsole", pid: 1234},
    windowActivated: {connect: (handler) => { activated = handler; }},
};
eval(fs.readFileSync(process.argv[1], "utf8"));
activated({resourceClass: "org.mozilla.firefox", resourceName: "firefox", pid: 4321});
activated(null);
activated({resourceClass: "", resourceName: "xwaylandvideobridge", pid: undefined});
console.log(JSON.stringify(calls.map((c) => [...c, c.slice(4).map((a) => Number.isInteger(a) ? "int" : typeof a)])));
"""


def test_metadata():
    metadata = json.loads((PACKAGE / "metadata.json").read_text())

    assert metadata["KPackageStructure"] == "KWin/Script"
    assert metadata["KPlugin"]["Id"] == PACKAGE.name == "plasmaar-focus"
    assert metadata["X-Plasma-API"] == "javascript"
    assert (PACKAGE / "contents" / metadata["X-Plasma-MainScript"]) == MAIN_SCRIPT


def test_reports_the_active_window_at_load_and_on_every_activation():
    if shutil.which("node") is None:
        pytest.skip("node is not available to run the KWin script")
    result = subprocess.run(["node", "-e", _HARNESS, str(MAIN_SCRIPT)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr

    calls = json.loads(result.stdout)

    target = [dbus_service.BUS_NAME, dbus_service.OBJECT_PATH, dbus_service.INTERFACE, "SetActiveWindow"]
    assert [call[:4] for call in calls] == [target] * 4
    assert [call[4:7] for call in calls] == [
        ["org.kde.konsole", "konsole", 1234],
        ["org.mozilla.firefox", "firefox", 4321],
        ["", "", 0],
        ["", "xwaylandvideobridge", 0],
    ]
    # matches SetActiveWindow(s, s, i) in the D-Bus API: always two strings and an integer
    assert all(call[7] == ["string", "string", "int"] for call in calls)


def test_dbus_api_declares_set_active_window_as_called_by_the_script():
    from gi.repository import Gio

    interface = Gio.DBusNodeInfo.new_for_xml(dbus_service.INTROSPECTION_XML).interfaces[0]
    method = interface.lookup_method("SetActiveWindow")

    assert [arg.signature for arg in method.in_args] == ["s", "s", "i"]
    assert not method.out_args
