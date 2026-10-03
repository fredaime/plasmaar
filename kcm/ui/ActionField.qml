// SPDX-FileCopyrightText: 2026 plasmaar contributors
// SPDX-License-Identifier: GPL-2.0-or-later

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import io.github.fredaime.plasmaar

// A KDE action ({component, action} or null) shown by its localized label, with buttons to change or remove it.
RowLayout {
    id: field

    required property var action
    required property Controller controller
    property bool editable: true
    property int fieldWidth: Kirigami.Units.gridUnit * 16

    signal pickRequested()
    signal picked(var action)

    readonly property bool hasAction: action !== null && action !== undefined && action.component !== undefined

    spacing: Kirigami.Units.smallSpacing

    QQC2.Button {
        id: choose
        Layout.preferredWidth: field.fieldWidth
        enabled: field.editable
        icon.name: field.hasAction ? "" : "list-add"
        text: {
            field.controller.kdeActions; // relabel once the action list arrives
            return field.hasAction ? field.controller.actionLabel(field.action) : i18nc("@action:button", "Choose an Action…");
        }
        onClicked: field.pickRequested()

        QQC2.ToolTip.visible: hovered && field.hasAction
        QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
        QQC2.ToolTip.text: field.hasAction ? i18nc("@info:tooltip KDE action: component, action id", "%1 › %2", field.action.component, field.action.action) : ""
    }

    QQC2.ToolButton {
        visible: field.hasAction
        enabled: field.editable
        icon.name: "edit-clear"
        display: QQC2.AbstractButton.IconOnly
        text: i18nc("@action:button", "Remove Action")
        onClicked: field.picked(null)

        QQC2.ToolTip.visible: hovered
        QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
        QQC2.ToolTip.text: text
    }
}
