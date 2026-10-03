/*
    SPDX-FileCopyrightText: 2026 plasmaar contributors
    SPDX-License-Identifier: GPL-2.0-or-later

    Reports the active window to plasmaard, so its rules (the Process condition) know which
    application has the focus on Plasma Wayland, where clients cannot ask for it themselves.
    See docs/desktop-events.md in the plasmaar repository.
*/

const SERVICE = "io.github.fredaime.Plasmaar";
const PATH = "/io/github/fredaime/Plasmaar";
const INTERFACE = "io.github.fredaime.Plasmaar1";

function report(window) {
    // SetActiveWindow(s resource_class, s resource_name, i pid); ("", "", 0) when no window is active.
    // "| 0" keeps the pid an integer, so it goes out as a D-Bus int32 and not a double.
    const resourceClass = window ? String(window.resourceClass || "") : "";
    const resourceName = window ? String(window.resourceName || "") : "";
    const pid = window ? window.pid | 0 : 0;
    // asynchronous; if plasmaard is not running the call just fails
    callDBus(SERVICE, PATH, INTERFACE, "SetActiveWindow", resourceClass, resourceName, pid);
}

workspace.windowActivated.connect(report);
report(workspace.activeWindow);
