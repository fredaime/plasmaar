// SPDX-FileCopyrightText: 2026 plasmaar contributors
// SPDX-License-Identifier: GPL-2.0-or-later

#include "stagedmodel.h"

#include "json.h"

namespace
{
const QString DefaultField = QStringLiteral("default");

QVariant nullValue()
{
    return QVariant::fromValue(nullptr);
}

bool isMap(const QVariant &value)
{
    return value.typeId() == QMetaType::QVariantMap;
}

QVariant setPath(const QVariant &target, const QStringList &path, int depth, const QVariant &value)
{
    if (depth == path.size()) {
        return value;
    }
    QVariantMap map = target.toMap();
    map.insert(path.at(depth), setPath(map.value(path.at(depth)), path, depth + 1, value));
    return map;
}
}

StagedModel::StagedModel(const QString &keyField, const QStringList &valueFields, const QStringList &fieldRoles, QObject *parent)
    : QAbstractListModel(parent)
    , m_keyField(keyField)
    , m_valueFields(valueFields)
    , m_fieldRoles(fieldRoles)
{
}

int StagedModel::rowCount(const QModelIndex &parent) const
{
    return parent.isValid() ? 0 : int(m_rows.size());
}

QHash<int, QByteArray> StagedModel::roleNames() const
{
    QHash<int, QByteArray> roles{
        {KeyRole, "key"},
        {EntryRole, "entry"},
        {ValueRole, "liveValue"},
        {PendingRole, "pending"},
        {ChangedRole, "changed"},
        {DefaultValueRole, "defaultValue"},
        {HasDefaultRole, "hasDefault"},
        {IsDefaultRole, "isDefault"},
        {ErrorRole, "writeError"},
        {BusyRole, "busy"},
    };
    for (int i = 0; i < m_fieldRoles.size(); ++i) {
        // "role=field" exposes an entry field under another role name
        roles.insert(FirstFieldRole + i, m_fieldRoles.at(i).section(QLatin1Char('='), 0, 0).toUtf8());
    }
    return roles;
}

QVariant StagedModel::data(const QModelIndex &index, int role) const
{
    if (!checkIndex(index, CheckIndexOption::IndexIsValid | CheckIndexOption::ParentIsInvalid)) {
        return {};
    }
    const Row &row = m_rows.at(index.row());
    switch (role) {
    case KeyRole:
        return keyOf(row.entry);
    case EntryRole:
        return row.entry;
    case ValueRole:
        return row.live;
    case PendingRole:
        return pendingOf(row);
    case ChangedRole:
        return isChanged(row);
    case DefaultValueRole:
        return row.entry.value(DefaultField);
    case HasDefaultRole:
        return row.entry.contains(DefaultField);
    case IsDefaultRole:
        return !row.entry.contains(DefaultField) || Json::equal(pendingOf(row), row.entry.value(DefaultField));
    case ErrorRole:
        return row.error;
    case BusyRole:
        return row.busy;
    default:
        break;
    }
    const int field = role - FirstFieldRole;
    if (field >= 0 && field < m_fieldRoles.size()) {
        const QString &spec = m_fieldRoles.at(field);
        return row.entry.value(spec.contains(QLatin1Char('=')) ? spec.section(QLatin1Char('='), 1) : spec);
    }
    return {};
}

int StagedModel::count() const
{
    return int(m_rows.size());
}

int StagedModel::revision() const
{
    return m_revision;
}

int StagedModel::stagingRevision() const
{
    return m_stagingRevision;
}

bool StagedModel::hasChanges() const
{
    return std::any_of(m_rows.cbegin(), m_rows.cend(), [this](const Row &row) {
        return isChanged(row);
    });
}

bool StagedModel::hasDefaults() const
{
    return std::any_of(m_rows.cbegin(), m_rows.cend(), [](const Row &row) {
        return row.entry.contains(DefaultField);
    });
}

bool StagedModel::atDefaults() const
{
    return std::all_of(m_rows.cbegin(), m_rows.cend(), [this](const Row &row) {
        return !row.entry.contains(DefaultField) || Json::equal(pendingOf(row), row.entry.value(DefaultField));
    });
}

bool StagedModel::hasErrors() const
{
    return std::any_of(m_rows.cbegin(), m_rows.cend(), [](const Row &row) {
        return !row.error.isEmpty();
    });
}

QString StagedModel::keyOf(const QVariantMap &entry) const
{
    return entry.value(m_keyField).toString();
}

QVariant StagedModel::valueOf(const QVariantMap &entry) const
{
    if (m_valueFields.size() == 1) {
        const QVariant value = entry.value(m_valueFields.first());
        return value.isValid() ? value : nullValue();
    }
    QVariantMap value;
    for (const QString &field : m_valueFields) {
        const QVariant fieldValue = entry.value(field);
        value.insert(field, fieldValue.isValid() ? fieldValue : nullValue());
    }
    return value;
}

QVariant StagedModel::pendingOf(const Row &row) const
{
    return row.staged.isValid() ? row.staged : row.live;
}

bool StagedModel::isChanged(const Row &row) const
{
    return row.staged.isValid() && !Json::equal(row.staged, row.live);
}

void StagedModel::setEntries(const QVariantList &entries, bool keepStaged)
{
    QHash<QString, QVariant> staged;
    if (keepStaged) {
        for (const Row &row : std::as_const(m_rows)) {
            if (row.staged.isValid()) {
                staged.insert(keyOf(row.entry), row.staged);
            }
        }
    }
    QList<Row> rows;
    rows.reserve(entries.size());
    for (const QVariant &item : entries) {
        Row row;
        row.entry = item.toMap();
        row.live = valueOf(row.entry);
        const QVariant edit = staged.value(keyOf(row.entry));
        if (edit.isValid() && !Json::equal(edit, row.live)) {
            row.staged = edit;
        }
        rows.append(row);
    }

    const bool sameKeys = !rows.isEmpty() && rows.size() == m_rows.size() && std::equal(rows.cbegin(), rows.cend(), m_rows.cbegin(), [this](const Row &a, const Row &b) {
                              return keyOf(a.entry) == keyOf(b.entry);
                          });
    if (sameKeys) {
        // The same entries again (a refresh): update the rows in place, so that views keep their delegates.
        for (qsizetype i = 0; i < rows.size(); ++i) {
            rows[i].error = m_rows.at(i).error;
        }
        m_rows = rows;
        QList<int> roles;
        const auto names = roleNames();
        for (auto it = names.cbegin(); it != names.cend(); ++it) {
            roles.append(it.key());
        }
        Q_EMIT dataChanged(index(0, 0), index(int(m_rows.size()) - 1, 0), roles);
        ++m_stagingRevision;
        Q_EMIT stateChanged();
        return;
    }

    const qsizetype oldCount = m_rows.size();
    beginResetModel();
    m_rows = rows;
    endResetModel();
    ++m_revision;
    ++m_stagingRevision;
    if (oldCount != m_rows.size()) {
        Q_EMIT countChanged();
    }
    Q_EMIT entriesReset();
    Q_EMIT stateChanged();
}

QVariantList StagedModel::entries() const
{
    QVariantList result;
    result.reserve(m_rows.size());
    for (const Row &row : m_rows) {
        result.append(row.entry);
    }
    return result;
}

bool StagedModel::setLiveValue(const QString &key, const QVariant &value)
{
    const int index = indexOf(key);
    if (index < 0) {
        return false;
    }
    Row &row = m_rows[index];
    bool fieldsChanged = false;
    if (m_valueFields.size() == 1) {
        row.entry.insert(m_valueFields.first(), value.isValid() ? value : nullValue());
        fieldsChanged = row.entry.remove(QStringLiteral("error")) > 0; // a value arrived, so it can be read now
    } else {
        const QVariantMap fields = value.toMap();
        for (auto it = fields.cbegin(); it != fields.cend(); ++it) {
            row.entry.insert(it.key(), it.value());
        }
    }
    applyLive(index, valueOf(row.entry), fieldsChanged);
    return true;
}

bool StagedModel::setLiveEntry(const QVariantMap &entry)
{
    const int index = indexOf(keyOf(entry));
    if (index < 0) {
        return false;
    }
    Row &row = m_rows[index];
    for (auto it = entry.cbegin(); it != entry.cend(); ++it) {
        row.entry.insert(it.key(), it.value());
    }
    applyLive(index, valueOf(row.entry), true);
    return true;
}

void StagedModel::applyLive(int index, const QVariant &newLive, bool fieldsChanged)
{
    Row &row = m_rows[index];
    if (row.staged.isValid() && isMap(row.staged) && isMap(row.live) && isMap(newLive)) {
        // keep the keys the user edited, take the others from the service
        const QVariantMap oldLive = row.live.toMap();
        const QVariantMap staged = row.staged.toMap();
        QVariantMap merged = newLive.toMap();
        for (auto it = staged.cbegin(); it != staged.cend(); ++it) {
            if (!Json::equal(it.value(), oldLive.value(it.key()))) {
                merged.insert(it.key(), it.value());
            }
        }
        row.staged = merged;
    }
    row.live = newLive;
    if (row.staged.isValid() && Json::equal(row.staged, row.live)) {
        row.staged = QVariant();
    }
    emitRowChanged(index, fieldsChanged);
}

int StagedModel::indexOf(const QString &key) const
{
    for (int i = 0; i < m_rows.size(); ++i) {
        if (keyOf(m_rows.at(i).entry) == key) {
            return i;
        }
    }
    return -1;
}

QVariantMap StagedModel::get(int row) const
{
    return row >= 0 && row < m_rows.size() ? m_rows.at(row).entry : QVariantMap();
}

QVariant StagedModel::field(int row, const QString &field) const
{
    return row >= 0 && row < m_rows.size() ? m_rows.at(row).entry.value(field) : QVariant();
}

QVariant StagedModel::pendingValue(int row) const
{
    return row >= 0 && row < m_rows.size() ? pendingOf(m_rows.at(row)) : QVariant();
}

QVariant StagedModel::liveValue(int row) const
{
    return row >= 0 && row < m_rows.size() ? m_rows.at(row).live : QVariant();
}

QString StagedModel::writeError(int row) const
{
    return row >= 0 && row < m_rows.size() ? m_rows.at(row).error : QString();
}

void StagedModel::stage(int row, const QVariant &value)
{
    stageRow(row, value);
}

void StagedModel::stageKey(int row, const QString &key, const QVariant &value)
{
    stagePath(row, {key}, value);
}

void StagedModel::stagePath(int row, const QStringList &path, const QVariant &value)
{
    if (row < 0 || row >= m_rows.size()) {
        return;
    }
    stageRow(row, setPath(pendingOf(m_rows.at(row)), path, 0, value.isValid() ? value : nullValue()));
}

void StagedModel::unstage(int row)
{
    if (row < 0 || row >= m_rows.size() || !m_rows.at(row).staged.isValid()) {
        return;
    }
    m_rows[row].staged = QVariant();
    emitRowChanged(row);
}

void StagedModel::stageRow(int index, const QVariant &value)
{
    if (index < 0 || index >= m_rows.size()) {
        return;
    }
    Row &row = m_rows[index];
    const QVariant newValue = value.isValid() ? value : nullValue();
    row.staged = Json::equal(newValue, row.live) ? QVariant() : newValue;
    row.error.clear();
    emitRowChanged(index);
}

void StagedModel::discard()
{
    for (int i = 0; i < m_rows.size(); ++i) {
        Row &row = m_rows[i];
        if (row.staged.isValid() || !row.error.isEmpty()) {
            row.staged = QVariant();
            row.error.clear();
            emitRowChanged(i);
        }
    }
}

void StagedModel::stageDefaults()
{
    for (int i = 0; i < m_rows.size(); ++i) {
        if (m_rows.at(i).entry.contains(DefaultField)) {
            stageRow(i, m_rows.at(i).entry.value(DefaultField));
        }
    }
}

QList<StagedModel::Change> StagedModel::changes() const
{
    QList<Change> result;
    for (int i = 0; i < m_rows.size(); ++i) {
        const Row &row = m_rows.at(i);
        if (!isChanged(row)) {
            continue;
        }
        Change change{i, keyOf(row.entry), row.live, row.staged, row.entry, {}};
        if (isMap(row.live) && isMap(row.staged)) {
            const QVariantMap live = row.live.toMap();
            const QVariantMap staged = row.staged.toMap();
            for (auto it = staged.cbegin(); it != staged.cend(); ++it) {
                if (!Json::equal(it.value(), live.value(it.key()))) {
                    change.changedKeys.append(it.key());
                }
            }
        }
        result.append(change);
    }
    return result;
}

void StagedModel::setError(int row, const QString &message)
{
    if (row < 0 || row >= m_rows.size() || m_rows.at(row).error == message) {
        return;
    }
    m_rows[row].error = message;
    emitRowChanged(row);
}

void StagedModel::clearErrors()
{
    for (int i = 0; i < m_rows.size(); ++i) {
        setError(i, QString());
    }
}

void StagedModel::setBusy(int row, bool busy)
{
    if (row < 0 || row >= m_rows.size() || m_rows.at(row).busy == busy) {
        return;
    }
    m_rows[row].busy = busy;
    const QModelIndex index = createIndex(row, 0);
    Q_EMIT dataChanged(index, index, {BusyRole});
    ++m_stagingRevision;
    Q_EMIT stateChanged();
}

void StagedModel::emitRowChanged(int row, bool fieldsChanged)
{
    // The field roles only when asked: they rarely change and may be large (per-key choice lists), and
    // re-reading them rebuilds their JavaScript copies in every delegate.
    QList<int> roles{EntryRole, ValueRole, PendingRole, ChangedRole, DefaultValueRole, HasDefaultRole, IsDefaultRole, ErrorRole, BusyRole};
    if (fieldsChanged) {
        for (int i = 0; i < m_fieldRoles.size(); ++i) {
            roles.append(FirstFieldRole + i);
        }
    }
    const QModelIndex index = createIndex(row, 0);
    Q_EMIT dataChanged(index, index, roles);
    ++m_stagingRevision;
    Q_EMIT stateChanged();
}

#include "moc_stagedmodel.cpp"
