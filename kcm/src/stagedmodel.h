// SPDX-FileCopyrightText: 2026 plasmaar contributors
// SPDX-License-Identifier: GPL-2.0-or-later

#pragma once

#include <QAbstractListModel>
#include <QList>
#include <QStringList>
#include <QVariant>
#include <qqmlregistration.h>

/*
 * A list of entries (settings, buttons, haptic events) as plasmaard describes them, with edits staged
 * until the KCM is applied.
 *
 * Every row keeps the entry's live value (what the service reports) and an optional staged value. QML
 * shows `pending` (staged if any, else live) and stages edits; save() writes the rows whose staged value
 * differs from the live one, and the service's answer (or its change signal) becomes the new live value.
 * Staging the live value again unstages the row, so needsSave really means "something would change".
 *
 * The value of a row is one field of the entry (`value` for settings, `waveform` for haptic events) or,
 * with several value fields, a map of them (mode/press/gestures for buttons). Map values can be edited
 * key by key (per-key settings, gesture directions): a live update then keeps the user's edited keys and
 * takes the others from the service.
 */
class StagedModel : public QAbstractListModel
{
    Q_OBJECT
    QML_ELEMENT
    QML_UNCREATABLE("Provided by the Controller")

    Q_PROPERTY(int count READ count NOTIFY countChanged)
    Q_PROPERTY(int revision READ revision NOTIFY entriesReset) // bumped whenever the entries are replaced
    Q_PROPERTY(int stagingRevision READ stagingRevision NOTIFY stateChanged) // bumped on every change of a row
    Q_PROPERTY(bool hasChanges READ hasChanges NOTIFY stateChanged)
    Q_PROPERTY(bool hasDefaults READ hasDefaults NOTIFY stateChanged)
    Q_PROPERTY(bool atDefaults READ atDefaults NOTIFY stateChanged)
    Q_PROPERTY(bool hasErrors READ hasErrors NOTIFY stateChanged)

public:
    enum Role {
        KeyRole = Qt::UserRole + 1, // the entry's id (setting name, button control, event name), as a string
        EntryRole, // the whole entry map
        ValueRole, // live value
        PendingRole, // staged value, or the live value
        ChangedRole, // a staged edit differs from the live value
        DefaultValueRole, // the entry's "default", if any
        HasDefaultRole,
        IsDefaultRole, // pending equals the default (true when there is no default)
        ErrorRole, // last write error for this row
        BusyRole, // a write is in flight
        FirstFieldRole, // then one role per field listed in the constructor
    };
    Q_ENUM(Role)

    struct Change {
        int row;
        QString key;
        QVariant live;
        QVariant pending;
        QVariantMap entry;
        QStringList changedKeys; // for map values: the keys whose value differs
    };

    StagedModel(const QString &keyField, const QStringList &valueFields, const QStringList &fieldRoles, QObject *parent = nullptr);

    int rowCount(const QModelIndex &parent = QModelIndex()) const override;
    QVariant data(const QModelIndex &index, int role) const override;
    QHash<int, QByteArray> roleNames() const override;

    int count() const;
    int revision() const;
    int stagingRevision() const;
    bool hasChanges() const;
    bool hasDefaults() const;
    bool atDefaults() const;
    bool hasErrors() const;

    // Replace all entries. With keepStaged, edits of rows that still exist survive (a refresh).
    void setEntries(const QVariantList &entries, bool keepStaged = false);
    QVariantList entries() const;

    // The service reports a new live value for an entry (signal or write reply).
    bool setLiveValue(const QString &key, const QVariant &value);
    // The service sent a whole new entry (e.g. a button after SetButtonAction).
    bool setLiveEntry(const QVariantMap &entry);

    Q_INVOKABLE int indexOf(const QString &key) const;
    Q_INVOKABLE QVariantMap get(int row) const; // the entry
    Q_INVOKABLE QVariant field(int row, const QString &field) const; // one field of the entry (cheaper)
    Q_INVOKABLE QVariant pendingValue(int row) const;
    Q_INVOKABLE QVariant liveValue(int row) const;
    Q_INVOKABLE QString writeError(int row) const;

    // Edits from QML.
    Q_INVOKABLE void stage(int row, const QVariant &value);
    Q_INVOKABLE void stageKey(int row, const QString &key, const QVariant &value);
    Q_INVOKABLE void stagePath(int row, const QStringList &path, const QVariant &value);
    Q_INVOKABLE void unstage(int row);

    void discard(); // drop all staged edits
    void stageDefaults(); // stage every row's default
    QList<Change> changes() const;

    void setError(int row, const QString &message);
    void clearErrors();
    void setBusy(int row, bool busy);

Q_SIGNALS:
    void countChanged();
    void entriesReset();
    void stateChanged();

private:
    struct Row {
        QVariantMap entry;
        QVariant live;
        QVariant staged; // invalid: nothing staged
        QString error;
        bool busy = false;
    };

    QString keyOf(const QVariantMap &entry) const;
    QVariant valueOf(const QVariantMap &entry) const;
    QVariant pendingOf(const Row &row) const;
    bool isChanged(const Row &row) const;
    void stageRow(int row, const QVariant &value);
    void applyLive(int row, const QVariant &newLive, bool fieldsChanged);
    void emitRowChanged(int row, bool fieldsChanged = false);

    QString m_keyField;
    QStringList m_valueFields;
    QStringList m_fieldRoles;
    QList<Row> m_rows;
    int m_revision = 0;
    int m_stagingRevision = 0;
};
