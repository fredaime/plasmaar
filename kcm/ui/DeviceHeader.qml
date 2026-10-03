// SPDX-FileCopyrightText: 2026 plasmaar contributors
// SPDX-License-Identifier: GPL-2.0-or-later

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import io.github.fredaime.plasmaar

// The selected device: picture, name, connection, battery, ids; and the device picker.
RowLayout {
    id: header

    required property Controller controller

    readonly property var device: controller.currentDevice
    readonly property bool online: device.online === true
    readonly property var battery: device.battery ?? {}
    readonly property bool batteryKnown: typeof battery.level === "number"
    readonly property bool charging: battery.status === "RECHARGING" || battery.status === "SLOW_RECHARGE"

    function iconFor(kind: string): string {
        switch (kind) {
        case "keyboard":
            return "input-keyboard";
        case "trackball":
        case "touchpad":
            return "input-touchpad";
        case "headset":
            return "audio-headset";
        default:
            return "input-mouse";
        }
    }

    function batteryIcon(): string {
        if (!batteryKnown) {
            return "battery-missing";
        }
        const level = Math.max(0, Math.min(100, Math.round(battery.level / 10) * 10));
        return "battery-" + String(level).padStart(3, "0") + (charging ? "-charging" : "");
    }

    function batteryStatus(): string {
        switch (battery.status) {
        case "DISCHARGING":
            return i18nc("@info battery state", "discharging");
        case "RECHARGING":
        case "SLOW_RECHARGE":
            return i18nc("@info battery state", "charging");
        case "FULL":
            return i18nc("@info battery state", "fully charged");
        case "ALMOST_FULL":
            return i18nc("@info battery state", "almost full");
        case "INVALID_BATTERY":
        case "THERMAL_ERROR":
        case "UNKNOWN_ERROR":
            return i18nc("@info battery state", "battery error");
        default:
            return "";
        }
    }

    function deviceLabel(entry: var): string {
        return entry.online ? entry.name : i18nc("@item:inlistbox device that is switched off", "%1 (offline)", entry.name);
    }

    spacing: Kirigami.Units.largeSpacing

    Kirigami.Icon {
        Layout.alignment: Qt.AlignTop
        implicitWidth: Kirigami.Units.iconSizes.huge
        implicitHeight: Kirigami.Units.iconSizes.huge
        source: header.iconFor(header.device.kind ?? "")
        opacity: header.online ? 1 : 0.6
    }

    ColumnLayout {
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing

        Kirigami.Heading {
            Layout.fillWidth: true
            level: 2
            text: header.device.name ?? ""
            elide: Text.ElideRight
        }

        RowLayout {
            spacing: Kirigami.Units.smallSpacing

            Rectangle {
                implicitWidth: Kirigami.Units.smallSpacing * 2
                implicitHeight: implicitWidth
                radius: width / 2
                color: header.online ? Kirigami.Theme.positiveTextColor : Kirigami.Theme.disabledTextColor
            }
            QQC2.Label {
                text: header.online ? i18nc("@info device state", "Connected") : i18nc("@info device state", "Offline: switched off, asleep or out of range")
            }

            Kirigami.Icon {
                Layout.leftMargin: Kirigami.Units.largeSpacing
                implicitWidth: Kirigami.Units.iconSizes.small
                implicitHeight: Kirigami.Units.iconSizes.small
                visible: header.batteryKnown
                source: header.batteryIcon()
            }
            QQC2.Label {
                visible: header.batteryKnown
                text: {
                    if (!header.batteryKnown) {
                        return "";
                    }
                    const level = i18nc("@info battery level", "%1%", header.battery.level);
                    const status = header.batteryStatus();
                    return status ? i18nc("@info battery level, state", "%1 (%2)", level, status) : level;
                }
            }
        }

        QQC2.Label {
            Layout.fillWidth: true
            font: Kirigami.Theme.smallFont
            color: Kirigami.Theme.disabledTextColor
            elide: Text.ElideRight
            text: {
                const parts = [];
                const device = header.device;
                if (device.codename && device.codename !== device.name) {
                    parts.push(device.codename);
                }
                if (device.model_id) {
                    parts.push(i18nc("@info device id", "Model %1", device.model_id));
                }
                if (device.unit_id) {
                    parts.push(i18nc("@info device id", "Unit %1", device.unit_id));
                }
                if (device.serial) {
                    parts.push(i18nc("@info device id", "Serial %1", device.serial));
                }
                if (device.protocol) {
                    parts.push(i18nc("@info protocol version", "HID++ %1", String(device.protocol)));
                }
                return parts.join(" · ");
            }
        }
    }

    QQC2.ComboBox {
        id: picker
        Layout.alignment: Qt.AlignTop
        Layout.maximumWidth: Kirigami.Units.gridUnit * 16
        visible: header.controller.devices.length > 1
        // switching would drop the edits, so they have to be applied or reset first
        enabled: !header.controller.needsSave && !header.controller.saving
        model: header.controller.devices.map(entry => ({
            id: entry.id,
            label: header.deviceLabel(entry)
        }))
        textRole: "label"
        valueRole: "id"
        currentIndex: header.controller.devices.findIndex(entry => entry.id === header.controller.currentDeviceId)
        onActivated: header.controller.currentDeviceId = currentValue

        QQC2.ToolTip.visible: hovered
        QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
        QQC2.ToolTip.text: enabled ? i18nc("@info:tooltip", "Choose the device to configure")
                                   : i18nc("@info:tooltip", "Apply or reset your changes before switching to another device")
    }
}
