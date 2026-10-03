// SPDX-FileCopyrightText: 2026 plasmaar contributors
// SPDX-License-Identifier: GPL-2.0-or-later

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM
import io.github.fredaime.plasmaar

KCM.SimpleKCM {
    id: root

    readonly property Controller controller: kcm.controller // qmllint disable unqualified

    readonly property bool serviceRunning: controller.serviceState === Controller.ServiceState.Running
    readonly property bool hasDevice: serviceRunning && controller.currentDeviceId !== ""
    readonly property bool pagesShown: hasDevice && !controller.loading

    // the pages that make sense for the current device
    readonly property var pages: {
        const result = [{
            id: "settings",
            title: i18nc("@title:tab", "Settings"),
            icon: "configure"
        }];
        const buttons = controller.buttonsState;
        if (buttons === Controller.FeatureState.Available || buttons === Controller.FeatureState.Failed
                || (buttons === Controller.FeatureState.NeedsNewerService && settingsHave("divert-keys"))) {
            result.push({
                id: "buttons",
                title: controller.currentDevice.kind === "keyboard" ? i18nc("@title:tab keyboard keys", "Keys") : i18nc("@title:tab", "Buttons"),
                icon: "input-mouse-click-left"
            });
        }
        if (settingsHave("haptic-level") || controller.waveforms.length > 0
                || controller.hapticEventsState === Controller.FeatureState.Available) {
            result.push({
                id: "haptics",
                title: i18nc("@title:tab", "Haptic Feedback"),
                icon: "preferences-desktop-notification-bell"
            });
        }
        return result;
    }
    property string currentPage: "settings"
    onPagesChanged: {
        if (!pages.some(page => page.id === currentPage)) {
            currentPage = "settings";
        }
    }

    // the KDE actions as picker entries, grouped by component
    readonly property var actionEntries: {
        const entries = [];
        for (const component of controller.kdeActions) {
            for (const action of component.actions ?? []) {
                entries.push({
                    value: {
                        component: component.component,
                        action: action.name
                    },
                    label: action.label || action.name,
                    section: component.label || component.component,
                    keywords: `${action.name} ${component.component}`
                });
            }
        }
        return entries;
    }

    function settingsHave(name: string): bool {
        controller.settings.count; // re-evaluate when the settings change
        return controller.settings.indexOf(name) >= 0;
    }

    implicitWidth: Kirigami.Units.gridUnit * 40
    implicitHeight: Kirigami.Units.gridUnit * 36

    header: ColumnLayout {
        visible: root.hasDevice
        spacing: 0

        DeviceHeader {
            Layout.fillWidth: true
            Layout.margins: Kirigami.Units.largeSpacing
            controller: root.controller
        }

        QQC2.TabBar {
            id: tabBar
            Layout.fillWidth: true
            visible: root.pages.length > 1
            currentIndex: root.pages.findIndex(page => page.id === root.currentPage)
            onCurrentIndexChanged: {
                if (currentIndex >= 0 && currentIndex < root.pages.length) {
                    root.currentPage = root.pages[currentIndex].id;
                }
            }

            QQC2.TabButton {
                text: root.pages[0].title
                icon.name: root.pages[0].icon
            }

            Repeater {
                model: root.pages.slice(1)
                delegate: QQC2.TabButton {
                    required property var modelData
                    text: modelData.title
                    icon.name: modelData.icon
                }
            }
        }

        Kirigami.Separator {
            Layout.fillWidth: true
            visible: !tabBar.visible
        }
    }

    ColumnLayout {
        id: content
        spacing: Kirigami.Units.largeSpacing

        Kirigami.InlineMessage {
            Layout.fillWidth: true
            type: Kirigami.MessageType.Error
            text: root.controller.saveError
            visible: text !== ""
            showCloseButton: true
        }

        Kirigami.InlineMessage {
            Layout.fillWidth: true
            type: Kirigami.MessageType.Warning
            text: root.controller.notice
            visible: text !== "" && root.currentPage !== "haptics"
            showCloseButton: true
            onVisibleChanged: if (!visible) root.controller.clearNotice()
        }

        // The pages of the current device. They are rebuilt for another device (while it loads), rather
        // than having all their rows replaced under the form layouts.
        Loader {
            Layout.fillWidth: true
            active: root.pagesShown
            visible: active

            sourceComponent: ColumnLayout {
                spacing: Kirigami.Units.largeSpacing

                SettingsPage {
                    Layout.fillWidth: true
                    visible: root.currentPage === "settings"
                    controller: root.controller
                    choiceDialog: choicePicker
                }

                ButtonsPage {
                    Layout.fillWidth: true
                    visible: root.currentPage === "buttons"
                    controller: root.controller
                    actionDialog: actionPicker
                    actionEntries: root.actionEntries
                }

                HapticsPage {
                    Layout.fillWidth: true
                    visible: root.currentPage === "haptics"
                    controller: root.controller
                    choiceDialog: choicePicker
                }
            }
        }

        // --- no device to show ---

        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: root.flickable.height - Kirigami.Units.largeSpacing * 4
            visible: !root.pagesShown

            Kirigami.LoadingPlaceholder {
                anchors.centerIn: parent
                visible: root.controller.serviceState === Controller.ServiceState.Checking
                    || (root.serviceRunning && root.controller.loading)
                text: i18nc("@info:placeholder", "Connecting to plasmaard…")
            }

            Kirigami.PlaceholderMessage {
                anchors.centerIn: parent
                width: parent.width - Kirigami.Units.gridUnit * 4
                visible: root.controller.serviceState === Controller.ServiceState.Missing
                icon.name: "input-mouse"
                text: i18nc("@info:placeholder", "The plasmaard service is not running")
                explanation: xi18nc("@info:placeholder",
                    "Logitech devices are managed by the plasmaard user service. Start it here, or in a terminal with <command>systemctl --user start plasmaard</command>.<nl/>It starts with your Plasma session once it is installed with <command>make install_user_service</command>.")
                helpfulAction: Kirigami.Action {
                    icon.name: "media-playback-start"
                    text: i18nc("@action:button", "Start plasmaard")
                    onTriggered: root.controller.startService()
                }
            }

            Kirigami.PlaceholderMessage {
                anchors.centerIn: parent
                width: parent.width - Kirigami.Units.gridUnit * 4
                visible: root.serviceRunning && root.controller.ready && root.controller.devices.length === 0
                icon.name: "input-mouse"
                text: i18nc("@info:placeholder", "No Logitech device found")
                explanation: i18nc("@info:placeholder", "Switch your mouse or keyboard on, or pair it with this computer over Bluetooth or a Logitech receiver.")
            }
        }
    }

    // shared pickers, opened by the pages
    PickerDialog {
        id: actionPicker
        searchPlaceholder: i18nc("@info:placeholder", "Search KDE actions…")
    }

    PickerDialog {
        id: choicePicker
        searchPlaceholder: i18nc("@info:placeholder", "Search…")
    }

    Loader {
        active: root.controller.snapshotPrefix !== ""
        sourceComponent: SnapshotRunner {
            page: root
            controller: root.controller
            actionDialog: actionPicker
        }
    }
}
