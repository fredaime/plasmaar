// SPDX-FileCopyrightText: 2026 plasmaar contributors
// SPDX-License-Identifier: GPL-2.0-or-later

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import io.github.fredaime.plasmaar

// The device's settings, drawn from the schema plasmaard sends, grouped in sections; per-key maps
// (button remapping and diversion) as a table at the end.
ColumnLayout {
    id: page

    required property Controller controller
    required property PickerDialog choiceDialog

    readonly property bool online: controller.currentDevice.online === true

    // on the haptics page instead
    readonly property var elsewhere: ["haptic-level", "haptic-play"]

    readonly property var allSections: [
        { id: "wheel", title: i18nc("@title:group", "Scroll Wheel") },
        { id: "thumb", title: i18nc("@title:group", "Thumb Wheel") },
        { id: "pointer", title: i18nc("@title:group", "Pointer") },
        { id: "buttons", title: i18nc("@title:group", "Buttons") },
        { id: "keyboard", title: i18nc("@title:group", "Keyboard") },
        { id: "lighting", title: i18nc("@title:group", "Lighting") },
        { id: "audio", title: i18nc("@title:group", "Audio") },
        { id: "connection", title: i18nc("@title:group", "Connection") },
        { id: "other", title: i18nc("@title:group", "Other Settings") }
    ]

    function sectionOf(name: string): string {
        if (name.startsWith("thumb-")) {
            return "thumb";
        }
        if (/^(hires-|hi-res-|lowres-|smooth-scroll|side-scroll|scroll-|smart-shift|divert-crown|crown-)/.test(name)) {
            return "wheel";
        }
        if (/^(dpi|pointer_speed|speed-change|report_rate|onboard_profiles)/.test(name)) {
            return "pointer";
        }
        if (/^(force-sensing|analog-button|divert-gkeys|gesture2-)/.test(name)) {
            return "buttons";
        }
        if (/^(fn-swap|multiplatform|disable-keyboard-keys|hand-detection)/.test(name)) {
            return "keyboard";
        }
        if (/^(backlight|led|rgb|brightness|m-key-leds|mr-key-led|per-key-lighting)/.test(name)) {
            return "lighting";
        }
        if (/^(headset|sidetone|equalizer|adc_power)/.test(name)) {
            return "audio";
        }
        if (name === "change-host") {
            return "connection";
        }
        return "other";
    }

    function inForm(name: string, kind: string, display: bool): bool {
        return display && kind !== "MAP_CHOICE" && !elsewhere.includes(name);
    }

    readonly property var sections: {
        const settings = controller.settings;
        settings.revision; // recompute when the device's settings are replaced
        const used = new Set();
        for (let i = 0; i < settings.count; ++i) {
            const name = settings.field(i, "name");
            if (inForm(name, settings.field(i, "kind"), settings.field(i, "display"))) {
                used.add(sectionOf(name));
            }
        }
        return allSections.filter(section => used.has(section.id));
    }

    spacing: Kirigami.Units.largeSpacing

    Kirigami.InlineMessage {
        Layout.fillWidth: true
        type: Kirigami.MessageType.Information
        visible: !page.online && page.controller.settings.count > 0
        text: i18nc("@info", "The device is offline. These are the last known values; switch it on or wake it up to change them.")
    }

    Kirigami.InlineMessage {
        Layout.fillWidth: true
        type: Kirigami.MessageType.Error
        visible: page.controller.settingsState === Controller.FeatureState.Failed
        text: i18nc("@info", "The settings could not be read: %1", page.controller.settingsError)
    }

    Kirigami.PlaceholderMessage {
        Layout.fillWidth: true
        Layout.margins: Kirigami.Units.gridUnit * 2
        visible: page.controller.settingsState === Controller.FeatureState.Unavailable
        icon.name: "configure"
        text: i18nc("@info:placeholder", "This device has no settings")
    }

    // the section layouts are twins of this one, so that all their labels line up
    Kirigami.FormLayout {
        id: anchorForm
        Layout.fillWidth: true
    }

    Repeater {
        model: page.sections

        delegate: Kirigami.FormLayout {
            id: sectionForm

            required property var modelData

            Layout.fillWidth: true
            twinFormLayouts: [anchorForm]

            Item {
                Kirigami.FormData.isSection: true
                Kirigami.FormData.label: sectionForm.modelData.title
            }

            Repeater {
                model: page.controller.settings

                delegate: SettingRow {
                    id: setting
                    required property bool display
                    controller: page.controller
                    choiceDialog: page.choiceDialog
                    visible: page.inForm(setting.name, setting.kind, setting.display)
                        && page.sectionOf(setting.name) === sectionForm.modelData.id
                }
            }
        }
    }

    KeyMapTable {
        Layout.fillWidth: true
        Layout.topMargin: Kirigami.Units.largeSpacing
        controller: page.controller
        choiceDialog: page.choiceDialog
    }
}
