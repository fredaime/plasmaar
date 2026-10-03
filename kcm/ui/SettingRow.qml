// SPDX-FileCopyrightText: 2026 plasmaar contributors
// SPDX-License-Identifier: GPL-2.0-or-later

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM
import io.github.fredaime.plasmaar

// One setting of the schema as a form row, drawn according to its kind. Edits are staged in the model.
ColumnLayout {
    id: row

    // from the settings model
    required property int index
    required property string name
    required property string label
    required property string description
    required property string kind
    required property bool writable
    required property var choices
    required property var min
    required property var max
    required property var pending
    required property bool isDefault
    required property string writeError
    required property var readError
    required property bool busy

    // from the page
    required property Controller controller
    required property PickerDialog choiceDialog

    readonly property bool readable: readError === undefined || readError === null
    readonly property bool online: controller.currentDevice.online === true
    readonly property bool editable: writable && readable && online && !controller.saving

    // choice lists: long numeric ones (dpi) become a stepped slider, long named ones a searchable list
    readonly property var choiceList: kind === "CHOICE" && choices ? Array.from(choices) : []
    readonly property bool numericChoices: choiceList.length > 12 && choiceList.every(choice => String(choice.value) === choice.name)
    readonly property int choiceIndex: choiceList.findIndex(choice => choice.value === pending)

    function stage(value: var): void {
        controller.settings.stage(index, value);
    }

    function summary(value: var): string {
        if (value === null || value === undefined) {
            return "";
        }
        if (typeof value === "boolean") {
            return value ? i18nc("@info setting value", "On") : i18nc("@info setting value", "Off");
        }
        if (typeof value === "object") {
            const keys = Object.keys(value);
            if (keys.length > 0 && keys.every(key => typeof value[key] === "boolean")) {
                // a set of flags (MULTIPLE_TOGGLE): the ones that are on
                const on = keys.filter(key => value[key]);
                return on.length > 0 ? on.join(", ") : i18nc("@info no flag is set", "None");
            }
            return keys.map(key => `${key}: ${row.summary(value[key])}`).join(", ");
        }
        return String(value);
    }

    spacing: Kirigami.Units.smallSpacing
    Kirigami.FormData.label: i18nc("@label:setting form label", "%1:", label)
    Kirigami.FormData.buddyFor: editor.item as Item

    RowLayout {
        spacing: Kirigami.Units.smallSpacing

        Loader {
            id: editor
            active: row.visible // rows of other sections stay empty
            enabled: row.editable // also greys out the form label
            sourceComponent: {
                if (!row.readable) {
                    return unreadable;
                }
                if (!row.writable) {
                    return readOnly;
                }
                switch (row.kind) {
                case "TOGGLE":
                    return toggle;
                case "RANGE":
                    return range;
                case "CHOICE":
                    if (row.numericChoices) {
                        return steppedChoice;
                    }
                    return row.choiceList.length > 40 ? searchableChoice : choice;
                default:
                    return readOnly;
                }
            }
        }

        Kirigami.ContextualHelpButton {
            visible: row.description !== ""
            toolTipText: row.description
        }

        QQC2.BusyIndicator {
            visible: row.busy
            running: visible
            implicitWidth: Kirigami.Units.iconSizes.small
            implicitHeight: Kirigami.Units.iconSizes.small
        }
    }

    QQC2.Label {
        Layout.fillWidth: true
        Layout.maximumWidth: Kirigami.Units.gridUnit * 16
        visible: row.writeError !== ""
        text: row.writeError
        color: Kirigami.Theme.negativeTextColor
        wrapMode: Text.Wrap
    }

    Component {
        id: toggle
        QQC2.Switch {
            checked: row.pending === true
            onToggled: row.stage(checked)
            KCM.SettingHighlighter {
                highlight: !row.isDefault
            }
        }
    }

    Component {
        id: choice
        QQC2.ComboBox {
            model: row.choiceList
            textRole: "name"
            valueRole: "value"
            currentIndex: row.choiceIndex
            onActivated: row.stage(currentValue)
            KCM.SettingHighlighter {
                highlight: !row.isDefault
            }
        }
    }

    Component {
        id: searchableChoice
        QQC2.Button {
            icon.name: "search"
            text: row.choiceIndex >= 0 ? row.choiceList[row.choiceIndex].name : row.summary(row.pending)
            onClicked: row.choiceDialog.pick(row.label, row.choiceList.map(entry => ({
                value: entry.value,
                label: entry.name,
                section: ""
            })), row.pending, value => row.stage(value))
            KCM.SettingHighlighter {
                highlight: !row.isDefault
            }
        }
    }

    Component {
        id: steppedChoice
        RowLayout {
            id: stepped
            spacing: Kirigami.Units.smallSpacing
            readonly property int step: row.choiceList.length > 1 ? row.choiceList[1].value - row.choiceList[0].value : 1

            function nearest(value: real): int {
                let best = row.choiceList[0].value;
                for (const entry of row.choiceList) {
                    if (Math.abs(entry.value - value) < Math.abs(best - value)) {
                        best = entry.value;
                    }
                }
                return best;
            }

            QQC2.Slider {
                Layout.preferredWidth: Kirigami.Units.gridUnit * 10
                from: 0
                to: row.choiceList.length - 1
                // no stepSize: too many steps for tick marks; moves are rounded to a choice
                value: Math.max(0, row.choiceIndex)
                onMoved: row.stage(row.choiceList[Math.round(value)].value)
                KCM.SettingHighlighter {
                    highlight: !row.isDefault
                }
            }
            QQC2.SpinBox {
                from: row.choiceList[0].value
                to: row.choiceList[row.choiceList.length - 1].value
                stepSize: Math.max(1, stepped.step)
                editable: true
                value: typeof row.pending === "number" ? row.pending : from
                onValueModified: row.stage(stepped.nearest(value))
            }
        }
    }

    Component {
        id: range
        RowLayout {
            spacing: Kirigami.Units.smallSpacing
            QQC2.Slider {
                Layout.preferredWidth: Kirigami.Units.gridUnit * 10
                from: row.min
                to: row.max
                // tick marks only for short ranges; moves are rounded to integers anyway
                stepSize: to - from > 20 ? 0 : 1
                value: typeof row.pending === "number" ? row.pending : row.min
                onMoved: row.stage(Math.round(value))
                KCM.SettingHighlighter {
                    highlight: !row.isDefault
                }
            }
            QQC2.SpinBox {
                from: row.min
                to: row.max
                editable: true
                value: typeof row.pending === "number" ? row.pending : row.min
                onValueModified: row.stage(value)
            }
        }
    }

    Component {
        id: readOnly
        QQC2.Label {
            text: {
                const value = row.summary(row.pending);
                return value ? i18nc("@info setting value that cannot be changed here", "%1 (read-only)", value) : i18nc("@info", "Read-only");
            }
            color: Kirigami.Theme.disabledTextColor
            wrapMode: Text.Wrap
            Layout.maximumWidth: Kirigami.Units.gridUnit * 20
        }
    }

    Component {
        id: unreadable
        QQC2.Label {
            text: row.online ? i18nc("@info", "Could not be read: %1", String(row.readError))
                             : i18nc("@info", "Unknown while the device is offline")
            color: Kirigami.Theme.disabledTextColor
            wrapMode: Text.Wrap
            Layout.maximumWidth: Kirigami.Units.gridUnit * 20
        }
    }
}
