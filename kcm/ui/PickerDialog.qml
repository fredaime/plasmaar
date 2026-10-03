// SPDX-FileCopyrightText: 2026 plasmaar contributors
// SPDX-License-Identifier: GPL-2.0-or-later

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

// A searchable list to pick one value from many: KDE actions (grouped by component) or long choice lists.
// One instance is shared by a page; pick() fills it and calls back with the chosen value.
Kirigami.SearchDialog {
    id: dialog

    property string searchPlaceholder
    property var entries: [] // [{value, label, section, keywords}]
    property var current: null
    property var callback: null

    function pick(context: string, list: var, currentValue: var, done: var): void {
        searchFieldPlaceholderText = context ? i18nc("@info:placeholder search field: what is being chosen", "Search: %1", context) : searchPlaceholder;
        entries = list;
        current = currentValue;
        callback = done;
        refill("");
        open();
    }

    function same(a: var, b: var): bool {
        return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
    }

    function refill(text: string): void {
        results.clear();
        const needle = text.trim().toLowerCase();
        const rows = [];
        entries.forEach((entry, index) => {
            const haystack = `${entry.label} ${entry.section ?? ""} ${entry.keywords ?? ""}`.toLowerCase();
            if (needle === "" || haystack.includes(needle)) {
                rows.push({
                    label: entry.label,
                    section: entry.section ?? "",
                    entryIndex: index,
                    isCurrent: same(entry.value, current)
                });
            }
        });
        results.append(rows);
    }

    function choose(entryIndex: int): void {
        const done = callback;
        const value = entries[entryIndex].value;
        close();
        if (done) {
            done(value);
        }
    }

    // as in SearchDialog, but safe while the window is torn down
    width: Math.min(Kirigami.Units.gridUnit * 35, (parent?.width ?? 0) - leftMargin - rightMargin)
    height: Math.min(Kirigami.Units.gridUnit * 20, parent?.height ?? 0)
    searchFieldPlaceholderText: searchPlaceholder
    emptyText: i18nc("@info:placeholder", "No match")

    onTextChanged: refill(text)
    onAccepted: {
        const item = currentItem as QQC2.ItemDelegate;
        if (item) {
            item.click();
        }
    }
    onClosed: callback = null

    model: ListModel {
        id: results
    }

    section.property: "section"
    section.delegate: Kirigami.ListSectionHeader {
        required property string section
        width: ListView.view.width
        text: section
        visible: section !== ""
        height: visible ? implicitHeight : 0
    }

    delegate: QQC2.ItemDelegate {
        required property string label
        required property int entryIndex
        required property bool isCurrent
        width: ListView.view.width
        text: label
        icon.name: isCurrent ? "checkmark" : ""
        highlighted: ListView.isCurrentItem
        onClicked: dialog.choose(entryIndex)
    }
}
