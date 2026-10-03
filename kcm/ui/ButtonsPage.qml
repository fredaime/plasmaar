// SPDX-FileCopyrightText: 2026 plasmaar contributors
// SPDX-License-Identifier: GPL-2.0-or-later

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import io.github.fredaime.plasmaar

// Divertable buttons: their mode (normal, action on press, gestures) and the KDE action for the press or
// for each gesture direction.
ColumnLayout {
    id: page

    required property Controller controller
    required property PickerDialog actionDialog

    readonly property bool canPick: controller.kdeActionsState === Controller.FeatureState.Available
    readonly property bool hasGestures: {
        const buttons = controller.buttons;
        buttons.revision;
        for (let i = 0; i < buttons.count; ++i) {
            if (Array.from(buttons.field(i, "modes") ?? []).includes("gesture")) {
                return true;
            }
        }
        return false;
    }
    // one width for the mode boxes and the action buttons, so that the column lines up
    readonly property int fieldWidth: Kirigami.Units.gridUnit * 16

    required property var actionEntries // see main.qml

    readonly property var directions: [
        { id: "up", label: i18nc("@label:chooser gesture direction", "Swipe up:") },
        { id: "down", label: i18nc("@label:chooser gesture direction", "Swipe down:") },
        { id: "left", label: i18nc("@label:chooser gesture direction", "Swipe left:") },
        { id: "right", label: i18nc("@label:chooser gesture direction", "Swipe right:") },
        { id: "click", label: i18nc("@label:chooser gesture button pressed and released without moving", "Click without swiping:") }
    ]

    function modeLabel(mode: string): string {
        switch (mode) {
        case "off":
            return i18nc("@item:inlistbox button mode", "Normal (its usual function)");
        case "press":
            return i18nc("@item:inlistbox button mode", "Run an action when pressed");
        case "gesture":
            return i18nc("@item:inlistbox button mode", "Gestures: hold, swipe and release");
        default:
            return mode;
        }
    }

    function pickAction(context: string, current: var, done: var): void {
        actionDialog.pick(context, actionEntries, current, done);
    }

    spacing: Kirigami.Units.largeSpacing

    Kirigami.PlaceholderMessage {
        Layout.fillWidth: true
        Layout.margins: Kirigami.Units.gridUnit * 2
        visible: page.controller.buttonsState === Controller.FeatureState.NeedsNewerService
        icon.name: "input-mouse"
        text: i18nc("@info:placeholder", "Button actions need a newer plasmaard")
        explanation: xi18nc("@info:placeholder",
            "The running plasmaard service cannot configure button actions yet. Update it, or map the buttons in <filename>~/.config/plasmaar/rules.yaml</filename> for now.")
    }

    Kirigami.InlineMessage {
        Layout.fillWidth: true
        type: Kirigami.MessageType.Error
        visible: page.controller.buttonsState === Controller.FeatureState.Failed
        text: i18nc("@info", "The button actions could not be read.")
    }

    Kirigami.InlineMessage {
        Layout.fillWidth: true
        type: Kirigami.MessageType.Warning
        visible: page.controller.buttonsState === Controller.FeatureState.Available
            && page.controller.kdeActionsState !== Controller.FeatureState.Available
            && page.controller.kdeActionsState !== Controller.FeatureState.Loading
        text: i18nc("@info", "The list of KDE actions is not available, so actions cannot be chosen right now.")
    }

    QQC2.Label {
        Layout.fillWidth: true
        Layout.leftMargin: Kirigami.Units.gridUnit * 2
        Layout.rightMargin: Kirigami.Units.gridUnit * 2
        visible: page.controller.buttonsState === Controller.FeatureState.Available
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
        color: Kirigami.Theme.disabledTextColor
        text: page.hasGestures
            ? i18nc("@info", "Buttons set to an action or to gestures run KDE Plasma actions instead of their usual function. For a gesture, hold the button, move the mouse in one direction and release it.")
            : i18nc("@info", "Keys set to an action run a KDE Plasma action instead of their usual function.")
    }

    // the button layouts are twins of this one, so that all their labels line up
    Kirigami.FormLayout {
        id: anchorForm
        Layout.fillWidth: true
    }

    Repeater {
        model: page.controller.buttons

        delegate: Kirigami.FormLayout {
            id: button

            required property int index
            required property string name
            required property var modes
            required property var pending
            required property string writeError
            required property bool busy

            readonly property string mode: pending.mode ?? "off"
            readonly property bool editable: !page.controller.saving

            Layout.fillWidth: true
            twinFormLayouts: [anchorForm]

            Item {
                Kirigami.FormData.isSection: true
                Kirigami.FormData.label: button.name
            }

            RowLayout {
                Kirigami.FormData.label: i18nc("@label:listbox", "Behavior:")
                spacing: Kirigami.Units.smallSpacing

                QQC2.ComboBox {
                    Layout.preferredWidth: page.fieldWidth
                    enabled: button.editable
                    model: button.modes.map(mode => ({
                        value: mode,
                        text: page.modeLabel(mode)
                    }))
                    textRole: "text"
                    valueRole: "value"
                    currentIndex: button.modes.indexOf(button.mode)
                    onActivated: page.controller.buttons.stageKey(button.index, "mode", currentValue)
                }

                QQC2.BusyIndicator {
                    visible: button.busy
                    running: visible
                    implicitWidth: Kirigami.Units.iconSizes.small
                    implicitHeight: Kirigami.Units.iconSizes.small
                }
            }

            ActionField {
                Kirigami.FormData.label: i18nc("@label:chooser", "Action:")
                fieldWidth: page.fieldWidth
                visible: button.mode === "press"
                controller: page.controller
                action: button.pending.press ?? null
                editable: button.editable && page.canPick
                onPickRequested: page.pickAction(button.name, action, value => page.controller.buttons.stageKey(button.index, "press", value))
                onPicked: value => page.controller.buttons.stageKey(button.index, "press", value)
            }

            Repeater {
                model: page.directions

                delegate: ActionField {
                    id: gesture
                    required property var modelData
                    Kirigami.FormData.label: modelData.label
                    fieldWidth: page.fieldWidth
                    visible: button.mode === "gesture"
                    controller: page.controller
                    action: button.pending.gestures?.[modelData.id] ?? null
                    editable: button.editable && page.canPick
                    onPickRequested: page.pickAction(i18nc("@info:placeholder button, gesture direction", "%1, %2", button.name, gesture.modelData.label.replace(/\s*:\s*$/, "")),
                        action, value => page.controller.buttons.stagePath(button.index, ["gestures", gesture.modelData.id], value))
                    onPicked: value => page.controller.buttons.stagePath(button.index, ["gestures", gesture.modelData.id], value)
                }
            }

            QQC2.Label {
                Layout.maximumWidth: Kirigami.Units.gridUnit * 20
                visible: button.writeError !== ""
                text: button.writeError
                color: Kirigami.Theme.negativeTextColor
                wrapMode: Text.Wrap
            }
        }
    }
}
