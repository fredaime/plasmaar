// SPDX-FileCopyrightText: 2026 plasmaar contributors
// SPDX-License-Identifier: GPL-2.0-or-later

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM
import io.github.fredaime.plasmaar

// Haptic feedback: intensity, a test button per waveform, and which waveform desktop events play.
ColumnLayout {
    id: page

    required property Controller controller
    required property PickerDialog choiceDialog

    readonly property bool online: controller.currentDevice.online === true
    readonly property var waveforms: controller.waveforms
    readonly property bool hasEvents: controller.hapticEventsState === Controller.FeatureState.Available

    // waveform names are device constants such as "SHARP STATE CHANGE"
    function waveformLabel(name: string): string {
        switch (name) {
        case "SHARP STATE CHANGE":
            return i18nc("@item haptic waveform", "Sharp state change");
        case "DAMP STATE CHANGE":
            return i18nc("@item haptic waveform", "Damped state change");
        case "SHARP COLLISION":
            return i18nc("@item haptic waveform", "Sharp collision");
        case "DAMP COLLISION":
            return i18nc("@item haptic waveform", "Damped collision");
        case "SUBTLE COLLISION":
            return i18nc("@item haptic waveform", "Subtle collision");
        case "WHISPER COLLISION":
            return i18nc("@item haptic waveform", "Whisper collision");
        case "HAPPY ALERT":
            return i18nc("@item haptic waveform", "Happy alert");
        case "ANGRY ALERT":
            return i18nc("@item haptic waveform", "Angry alert");
        case "COMPLETED":
            return i18nc("@item haptic waveform", "Completed");
        case "SQUARE":
            return i18nc("@item haptic waveform", "Square");
        case "WAVE":
            return i18nc("@item haptic waveform", "Wave");
        case "FIREWORK":
            return i18nc("@item haptic waveform", "Firework");
        case "MAD":
            return i18nc("@item haptic waveform", "Mad");
        case "KNOCK":
            return i18nc("@item haptic waveform", "Knock");
        case "JINGLE":
            return i18nc("@item haptic waveform", "Jingle");
        case "RINGING":
            return i18nc("@item haptic waveform", "Ringing");
        default:
            return name.charAt(0) + name.slice(1).toLowerCase();
        }
    }

    spacing: Kirigami.Units.largeSpacing

    Kirigami.InlineMessage {
        Layout.fillWidth: true
        type: Kirigami.MessageType.Warning
        text: page.controller.notice
        visible: text !== ""
        showCloseButton: true
        onVisibleChanged: if (!visible) page.controller.clearNotice()
    }

    Kirigami.InlineMessage {
        Layout.fillWidth: true
        type: Kirigami.MessageType.Information
        visible: !page.online
        text: i18nc("@info", "The device is offline. Switch it on or wake it up to feel the effects.")
    }

    Kirigami.FormLayout {
        Layout.fillWidth: true

        // the haptic-level setting, drawn like on the settings page
        Repeater {
            model: page.controller.settings
            delegate: SettingRow {
                id: level
                controller: page.controller
                choiceDialog: page.choiceDialog
                visible: level.name === "haptic-level"
                Kirigami.FormData.label: i18nc("@label:slider", "Intensity:")
            }
        }

        Item {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: i18nc("@title:group", "Try the Effects")
            visible: page.waveforms.length > 0
        }

        GridLayout {
            Kirigami.FormData.label: i18nc("@label", "Play:")
            Kirigami.FormData.buddyFor: waveformButtons.count > 0 ? waveformButtons.itemAt(0) : null
            visible: page.waveforms.length > 0
            columns: 2
            rowSpacing: Kirigami.Units.smallSpacing
            columnSpacing: Kirigami.Units.smallSpacing

            Repeater {
                id: waveformButtons
                model: page.waveforms
                delegate: QQC2.Button {
                    required property string modelData
                    Layout.fillWidth: true
                    enabled: page.online
                    icon.name: "media-playback-start"
                    text: page.waveformLabel(modelData)
                    onClicked: page.controller.playHaptic(modelData)
                }
            }
        }

        Item {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: i18nc("@title:group", "Desktop Events")
            visible: page.hasEvents
        }

        Repeater {
            model: page.hasEvents ? page.controller.hapticEvents : null

            delegate: RowLayout {
                id: event

                required property int index
                required property string label
                required property var pending
                required property bool isDefault
                required property string writeError
                required property bool busy

                Kirigami.FormData.label: i18nc("@label:listbox desktop event", "%1:", label)
                spacing: Kirigami.Units.smallSpacing

                QQC2.ComboBox {
                    id: waveformBox
                    enabled: !page.controller.saving
                    model: [{
                        value: "",
                        text: i18nc("@item:inlistbox no haptic effect", "None")
                    }].concat(page.waveforms.map(name => ({
                        value: name,
                        text: page.waveformLabel(name)
                    })))
                    textRole: "text"
                    valueRole: "value"
                    currentIndex: event.pending ? page.waveforms.indexOf(event.pending) + 1 : 0
                    onActivated: page.controller.hapticEvents.stage(event.index, currentValue === "" ? null : currentValue)
                }

                QQC2.ToolButton {
                    enabled: page.online && !!event.pending
                    icon.name: "media-playback-start"
                    display: QQC2.AbstractButton.IconOnly
                    text: i18nc("@action:button", "Try It")
                    onClicked: page.controller.playHaptic(event.pending)
                    QQC2.ToolTip.visible: hovered
                    QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
                    QQC2.ToolTip.text: text
                }

                QQC2.BusyIndicator {
                    visible: event.busy
                    running: visible
                    implicitWidth: Kirigami.Units.iconSizes.small
                    implicitHeight: Kirigami.Units.iconSizes.small
                }

                QQC2.Label {
                    visible: event.writeError !== ""
                    text: event.writeError
                    color: Kirigami.Theme.negativeTextColor
                }
            }
        }

        QQC2.Label {
            visible: page.controller.hapticEventsState === Controller.FeatureState.NeedsNewerService
            Layout.maximumWidth: Kirigami.Units.gridUnit * 20
            wrapMode: Text.Wrap
            color: Kirigami.Theme.disabledTextColor
            text: i18nc("@info", "Haptic feedback for desktop events needs a newer plasmaard.")
        }
    }
}
