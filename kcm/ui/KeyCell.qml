// SPDX-FileCopyrightText: 2026 plasmaar contributors
// SPDX-License-Identifier: GPL-2.0-or-later

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM

// The value of one key in a per-key setting: a combo box, a searchable list for long ones, or a spin box.
Item {
    id: keyCell

    required property var column // {label, keys: {key id: {value, name, choices | min, max}}}
    required property string keyId
    required property string keyName
    required property var value
    required property var defaultValue
    required property bool editable
    required property PickerDialog choiceDialog

    signal edited(var value)

    readonly property var space: column.keys[keyId]
    readonly property var choices: space.choices ? Array.from(space.choices) : []
    readonly property int choiceIndex: choices.findIndex(choice => choice.value === value)
    readonly property bool isDefault: defaultValue === undefined || defaultValue === value

    implicitWidth: loader.implicitWidth
    implicitHeight: loader.implicitHeight

    Loader {
        id: loader
        anchors.fill: parent
        sourceComponent: keyCell.space.choices === undefined ? spin : (keyCell.choices.length > 40 ? search : combo)
    }

    Component {
        id: combo
        QQC2.ComboBox {
            enabled: keyCell.editable
            model: keyCell.choices
            textRole: "name"
            valueRole: "value"
            currentIndex: keyCell.choiceIndex
            onActivated: keyCell.edited(currentValue)
            Accessible.name: i18nc("@label accessible name: setting, key", "%1, %2", keyCell.column.label, keyCell.keyName)
            KCM.SettingHighlighter {
                highlight: !keyCell.isDefault
            }
        }
    }

    Component {
        id: search
        QQC2.Button {
            enabled: keyCell.editable
            icon.name: "search"
            text: keyCell.choiceIndex >= 0 ? keyCell.choices[keyCell.choiceIndex].name : String(keyCell.value ?? "")
            onClicked: keyCell.choiceDialog.pick(i18nc("@title:window setting, key", "%1: %2", keyCell.column.label, keyCell.keyName),
                keyCell.choices.map(choice => ({
                    value: choice.value,
                    label: choice.name,
                    section: ""
                })), keyCell.value, value => keyCell.edited(value))
            Accessible.name: i18nc("@label accessible name: setting, key", "%1, %2", keyCell.column.label, keyCell.keyName)
            KCM.SettingHighlighter {
                highlight: !keyCell.isDefault
            }
        }
    }

    Component {
        id: spin
        QQC2.SpinBox {
            enabled: keyCell.editable
            from: keyCell.space.min ?? 0
            to: keyCell.space.max ?? 0
            editable: true
            value: typeof keyCell.value === "number" ? keyCell.value : from
            onValueModified: keyCell.edited(value)
            Accessible.name: i18nc("@label accessible name: setting, key", "%1, %2", keyCell.column.label, keyCell.keyName)
            KCM.SettingHighlighter {
                highlight: !keyCell.isDefault
            }
        }
    }
}
