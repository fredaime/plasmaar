// SPDX-FileCopyrightText: 2026 plasmaar contributors
// SPDX-License-Identifier: GPL-2.0-or-later

pragma ComponentBehavior: Bound

import QtQuick
import org.kde.kirigami as Kirigami
import io.github.fredaime.plasmaar

// Snapshot mode (PLASMAAR_KCM_SNAPSHOT=/path/prefix): once the data has loaded, show every page of every
// device, grow the window to fit it, save <prefix>-<device>-<page>.png, then quit. Used to review the
// module headless; see docs/kcm.md. It never writes to the service, except in the "apply-errors" scenario
// that kcm/run-snapshots.sh only enables against the mock service.
Item {
    id: runner

    required property var page // the KCM root page
    required property Controller controller
    required property PickerDialog actionDialog

    readonly property string prefix: controller.snapshotPrefix
    readonly property int windowWidth: 920
    property var steps: [] // functions; one that returns false runs again at the next tick
    property bool started: false

    function fitWindow(): void {
        const flickable = page.flickable;
        // contentHeight leaves out the page's padding: add some slack so that no scroll bar shows
        const overflow = Math.ceil(flickable.contentHeight - flickable.height) + Kirigami.Units.gridUnit * 2;
        controller.resizeTopLevelWindows(windowWidth, Math.max(560, controller.topLevelWindowHeight() + overflow));
    }

    function shoot(name: string): void {
        const path = `${prefix}-${name}.png`;
        console.info(controller.grabTopLevelWindow(path) ? `snapshot: ${path}` : `snapshot FAILED: ${path}`);
    }

    function slug(name: string): string {
        return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    }

    function loaded(): bool {
        return controller.ready && !controller.loading;
    }

    // the pages of the device that is shown, and the action picker if asked
    function pageSteps(device: string, withPicker: bool): var {
        const result = [];
        for (const entry of page.pages) {
            const id = entry.id;
            result.push(() => {
                page.currentPage = id;
                controller.resizeTopLevelWindows(windowWidth, 560);
            }, () => fitWindow(), () => shoot(`${device}-${id}`));
        }
        if (withPicker && page.pages.some(entry => entry.id === "buttons") && controller.buttons.count > 0
                && controller.kdeActionsState === Controller.FeatureState.Available) {
            result.push(() => {
                page.currentPage = "buttons";
                controller.resizeTopLevelWindows(windowWidth, 720);
            }, () => {
                const buttons = controller.buttons;
                const row = Math.max(0, buttons.indexOf("195"));
                actionDialog.pick(buttons.field(row, "name"), page.actionEntries, buttons.pendingValue(row).gestures?.up ?? null, () => {});
            }, () => shoot(`${device}-buttons-picker`), () => actionDialog.close());
        }
        return result;
    }

    function deviceSteps(index: int, withPicker: bool): var {
        const devices = controller.devices;
        if (index >= devices.length) {
            return [];
        }
        const device = devices[index];
        return [() => {
            page.currentPage = "settings";
            controller.currentDeviceId = device.id;
        }, () => {}, () => loaded(), () => {
            // planned now that the device's pages are known; the picker once, for the first device with buttons
            const picker = withPicker && controller.buttons.count > 0;
            steps = pageSteps(slug(device.name), picker).concat(deviceSteps(index + 1, withPicker && !picker), steps);
        }];
    }

    function plan(): var {
        if (!page.hasDevice) {
            return [() => fitWindow(), () => shoot(controller.serviceState === Controller.ServiceState.Missing ? "missing" : "empty")];
        }
        if (controller.snapshotScenario === "apply-errors") {
            // stage a few edits and apply them; the mock is started with --fail for some of them
            return [() => {
                const settings = controller.settings;
                settings.stage(settings.indexOf("dpi"), 2400);
                settings.stage(settings.indexOf("smart-shift"), 20);
                settings.stage(settings.indexOf("hires-smooth-invert"), true);
                controller.save();
            }, () => !controller.saving, () => {
                steps = pageSteps(`${slug(controller.currentDevice.name)}-apply-errors`, false).concat(steps);
            }];
        }
        return deviceSteps(0, true);
    }

    function step(): void {
        if (steps.length === 0) {
            controller.quitApplication();
            return;
        }
        const next = steps.shift();
        if (next() === false) {
            steps.unshift(next); // not yet
        }
        timer.restart();
    }

    Timer {
        id: timer
        interval: 500
        onTriggered: runner.step()
    }

    Timer {
        id: settle
        interval: 1000
        onTriggered: {
            runner.started = true;
            runner.steps = runner.plan();
            runner.step();
        }
    }

    Component.onCompleted: {
        if (controller.ready) {
            settle.start();
        }
    }

    Connections {
        target: runner.controller
        function onReadyChanged(): void {
            if (runner.controller.ready && !runner.started) {
                settle.restart();
            }
        }
    }
}
