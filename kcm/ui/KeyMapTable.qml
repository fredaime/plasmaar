// SPDX-FileCopyrightText: 2026 plasmaar contributors
// SPDX-License-Identifier: GPL-2.0-or-later

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM
import io.github.fredaime.plasmaar

// The per-key settings (MAP_CHOICE: reprogrammable-keys, divert-keys, …) side by side: one row per key or
// button, one column per setting.
ColumnLayout {
    id: table

    required property Controller controller
    required property PickerDialog choiceDialog

    readonly property bool online: controller.currentDevice.online === true

    readonly property var columns: {
        const settings = controller.settings;
        settings.revision;
        const result = [];
        for (let i = 0; i < settings.count; ++i) {
            if (settings.field(i, "kind") === "MAP_CHOICE" && settings.field(i, "display")) {
                const keys = {}; // key id -> {value, name, choices | min, max}
                const order = [];
                for (const key of Array.from(settings.field(i, "keys") ?? [])) {
                    keys[String(key.value)] = key;
                    order.push(String(key.value));
                }
                result.push({
                    row: i,
                    name: settings.field(i, "name"),
                    label: settings.field(i, "label"),
                    description: settings.field(i, "description"),
                    writable: settings.field(i, "writable") === true,
                    defaults: settings.field(i, "default") ?? null,
                    keys: keys,
                    order: order
                });
            }
        }
        return result;
    }

    // every key of every column, in the order the device lists them
    readonly property var keys: {
        const seen = new Map();
        for (const column of columns) {
            for (const value of column.order) {
                if (!seen.has(value)) {
                    seen.set(value, column.keys[value].name);
                }
            }
        }
        return Array.from(seen, ([value, name]) => ({ value, name }));
    }

    // the cells of the grid, row by row
    readonly property var cells: {
        const result = [{ type: "corner" }];
        for (const column of columns) {
            result.push({ type: "header", column });
        }
        for (const key of keys) {
            result.push({ type: "key", key });
            for (const column of columns) {
                result.push({ type: "cell", column, key });
            }
        }
        return result;
    }

    function pending(column: var): var {
        controller.settings.stagingRevision; // follow edits and live updates
        return controller.settings.pendingValue(column.row) ?? {};
    }

    function rowError(column: var): string {
        controller.settings.stagingRevision;
        return controller.settings.writeError(column.row);
    }

    readonly property int columnWidth: Kirigami.Units.gridUnit * 13

    visible: columns.length > 0
    spacing: Kirigami.Units.largeSpacing

    Kirigami.Heading {
        Layout.fillWidth: true // lets the table take the page's width, so that it is centered
        horizontalAlignment: Text.AlignHCenter
        level: 3
        type: Kirigami.Heading.Type.Primary
        text: i18nc("@title:group", "Keys and Buttons")
    }

    GridLayout {
        Layout.alignment: Qt.AlignHCenter
        Layout.fillWidth: false
        columns: table.columns.length + 1
        rowSpacing: Kirigami.Units.smallSpacing
        columnSpacing: Kirigami.Units.largeSpacing

        Repeater {
            model: table.cells

            delegate: Loader {
                id: cell
                required property var modelData
                Layout.alignment: modelData.type === "key" ? Qt.AlignRight | Qt.AlignVCenter : Qt.AlignLeft | Qt.AlignVCenter
                // fixed column widths; long key names (K850) and headers wrap
                Layout.fillWidth: false
                Layout.preferredWidth: modelData.type === "cell" || modelData.type === "header" ? table.columnWidth : -1
                Layout.maximumWidth: modelData.type === "key" ? Kirigami.Units.gridUnit * 13 : table.columnWidth
                sourceComponent: {
                    switch (modelData.type) {
                    case "header":
                        return header;
                    case "key":
                        return keyLabel;
                    case "cell":
                        return modelData.column.keys[modelData.key.value] !== undefined ? editor : null;
                    default:
                        return null;
                    }
                }

                Component {
                    id: header
                    ColumnLayout {
                        spacing: 0
                        RowLayout {
                            spacing: Kirigami.Units.smallSpacing
                            QQC2.Label {
                                Layout.fillWidth: true
                                text: cell.modelData.column.label
                                font.bold: true
                                wrapMode: Text.Wrap
                            }
                            Kirigami.ContextualHelpButton {
                                visible: cell.modelData.column.description !== ""
                                toolTipText: cell.modelData.column.description
                            }
                        }
                        QQC2.Label {
                            Layout.fillWidth: true
                            readonly property string error: table.rowError(cell.modelData.column)
                            visible: error !== ""
                            text: error
                            color: Kirigami.Theme.negativeTextColor
                            wrapMode: Text.Wrap
                        }
                    }
                }

                Component {
                    id: keyLabel
                    QQC2.Label {
                        text: i18nc("@label:key name in the key table", "%1:", cell.modelData.key.name)
                        horizontalAlignment: Text.AlignRight
                        wrapMode: Text.Wrap
                    }
                }

                Component {
                    id: editor
                    KeyCell {
                        column: cell.modelData.column
                        keyId: cell.modelData.key.value
                        keyName: cell.modelData.key.name
                        value: table.pending(cell.modelData.column)[cell.modelData.key.value]
                        defaultValue: cell.modelData.column.defaults === null ? undefined : cell.modelData.column.defaults[cell.modelData.key.value]
                        editable: cell.modelData.column.writable && table.online && !table.controller.saving
                        choiceDialog: table.choiceDialog
                        onEdited: value => table.controller.settings.stageKey(cell.modelData.column.row, cell.modelData.key.value, value)
                    }
                }
            }
        }
    }
}
