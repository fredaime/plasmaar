// SPDX-FileCopyrightText: 2026 plasmaar contributors
// SPDX-License-Identifier: GPL-2.0-or-later

// The staging rules behind the KCM's Apply/Reset/Defaults, without D-Bus.

#include "json.h"
#include "stagedmodel.h"

#include <QSignalSpy>
#include <QTest>

using namespace Qt::StringLiterals;

namespace
{
QVariantMap setting(const QString &name, const QVariant &value, const QVariant &defaultValue = {})
{
    QVariantMap entry{{u"name"_s, name}, {u"label"_s, name.toUpper()}, {u"value"_s, value}};
    if (defaultValue.isValid()) {
        entry.insert(u"default"_s, defaultValue);
    }
    return entry;
}

QVariantMap map(std::initializer_list<std::pair<QString, QVariant>> items)
{
    QVariantMap result;
    for (const auto &[key, value] : items) {
        result.insert(key, value);
    }
    return result;
}
}

class StagedModelTest : public QObject
{
    Q_OBJECT

private:
    StagedModel *settings(QObject *parent)
    {
        auto *model = new StagedModel(u"name"_s, {u"value"_s}, {u"name"_s, u"label"_s}, parent);
        model->setEntries({
            setting(u"dpi"_s, 1600, 1000),
            setting(u"smart-shift"_s, 12, 12),
            setting(u"change-host"_s, 2),
            setting(u"divert-keys"_s, map({{u"82"_s, 0}, {u"195"_s, 2}}), map({{u"82"_s, 0}, {u"195"_s, 0}})),
        });
        return model;
    }

private Q_SLOTS:
    void jsonRoundTrip()
    {
        QCOMPARE(Json::serialize(QVariant(2000.0)), u"2000"_s); // QML numbers are doubles
        QCOMPARE(Json::serialize(QVariant(true)), u"true"_s);
        QCOMPARE(Json::serialize(QVariant::fromValue(nullptr)), u"null"_s);
        QCOMPARE(Json::serialize(map({{u"mode"_s, u"press"_s}})), uR"({"mode":"press"})"_s);
        QCOMPARE(Json::parse(u"1200"_s).toInt(), 1200);
        QVERIFY(Json::parse(u"null"_s).isNull());
        bool ok = true;
        Json::parse(u"{oops"_s, &ok);
        QVERIFY(!ok);
        QVERIFY(Json::equal(QVariant(qlonglong(5)), QVariant(5.0)));
        QVERIFY(!Json::equal(QVariant(true), QVariant(1)));
        QVERIFY(Json::equal(map({{u"a"_s, 1}, {u"b"_s, 2}}), map({{u"b"_s, 2.0}, {u"a"_s, 1}})));
    }

    void stagingTheLiveValueUnstages()
    {
        QObject parent;
        StagedModel *model = settings(&parent);
        const int dpi = model->indexOf(u"dpi"_s);
        QVERIFY(!model->hasChanges());

        model->stage(dpi, 2000.0);
        QVERIFY(model->hasChanges());
        QCOMPARE(model->pendingValue(dpi).toInt(), 2000);
        QCOMPARE(model->liveValue(dpi).toInt(), 1600);
        QCOMPARE(model->data(model->index(dpi), StagedModel::ChangedRole).toBool(), true);

        model->stage(dpi, 1600.0); // back to what the device has: nothing to apply
        QVERIFY(!model->hasChanges());
        QCOMPARE(model->changes().size(), 0);
    }

    void perKeyEditsOnlyTouchTheirKey()
    {
        QObject parent;
        StagedModel *model = settings(&parent);
        const int row = model->indexOf(u"divert-keys"_s);

        model->stageKey(row, u"82"_s, 1);
        const auto changes = model->changes();
        QCOMPARE(changes.size(), 1);
        QCOMPARE(changes.first().changedKeys, QStringList{u"82"_s});
        QCOMPARE(changes.first().pending.toMap().value(u"195"_s).toInt(), 2);

        // the device changes another key meanwhile: the edit survives, the other key follows the device
        QVERIFY(model->setLiveValue(u"divert-keys"_s, map({{u"82"_s, 0}, {u"195"_s, 0}})));
        const QVariantMap pending = model->pendingValue(row).toMap();
        QCOMPARE(pending.value(u"82"_s).toInt(), 1);
        QCOMPARE(pending.value(u"195"_s).toInt(), 0);
        QCOMPARE(model->changes().first().changedKeys, QStringList{u"82"_s});

        // and once the device has the edited value, nothing is left to apply
        QVERIFY(model->setLiveValue(u"divert-keys"_s, map({{u"82"_s, 1}, {u"195"_s, 0}})));
        QVERIFY(!model->hasChanges());
    }

    void nestedPaths()
    {
        QObject parent;
        StagedModel model(u"control"_s, {u"mode"_s, u"press"_s, u"gestures"_s}, {u"name"_s}, &parent);
        model.setEntries({QVariantMap{
            {u"control"_s, 195},
            {u"name"_s, u"Gesture"_s},
            {u"mode"_s, u"off"_s},
            {u"press"_s, QVariant::fromValue(nullptr)},
            {u"gestures"_s, map({{u"up"_s, QVariant::fromValue(nullptr)}, {u"down"_s, QVariant::fromValue(nullptr)}})},
        }});
        const QVariantMap overview = map({{u"component"_s, u"kwin"_s}, {u"action"_s, u"Overview"_s}});
        model.stageKey(0, u"mode"_s, u"gesture"_s);
        model.stagePath(0, {u"gestures"_s, u"up"_s}, overview);
        const QVariantMap pending = model.pendingValue(0).toMap();
        QCOMPARE(pending.value(u"mode"_s).toString(), u"gesture"_s);
        QCOMPARE(pending.value(u"gestures"_s).toMap().value(u"up"_s).toMap(), overview);
        QVERIFY(pending.value(u"gestures"_s).toMap().value(u"down"_s).isNull());
        QCOMPARE(Json::serialize(pending.value(u"press"_s)), u"null"_s);

        // the service answers with the whole button: it becomes the live value
        QVariantMap reply = model.get(0);
        reply.insert(u"mode"_s, u"gesture"_s);
        reply.insert(u"gestures"_s, pending.value(u"gestures"_s));
        QVERIFY(model.setLiveEntry(reply));
        QVERIFY(!model.hasChanges());
    }

    void defaults()
    {
        QObject parent;
        StagedModel *model = settings(&parent);
        QVERIFY(model->hasDefaults());
        QVERIFY(!model->atDefaults()); // dpi and divert-keys differ

        model->stageDefaults();
        QVERIFY(model->atDefaults());
        QCOMPARE(model->pendingValue(model->indexOf(u"dpi"_s)).toInt(), 1000);
        QCOMPARE(model->pendingValue(model->indexOf(u"change-host"_s)).toInt(), 2); // no default: untouched
        QCOMPARE(model->changes().size(), 2);

        model->discard();
        QVERIFY(!model->hasChanges());
        QVERIFY(!model->atDefaults());

        StagedModel none(u"name"_s, {u"value"_s}, {}, &parent);
        none.setEntries({setting(u"change-host"_s, 2)});
        QVERIFY(!none.hasDefaults());
        QVERIFY(none.atDefaults());
    }

    void refreshKeepsRowsAndOptionallyEdits()
    {
        QObject parent;
        StagedModel *model = settings(&parent);
        const QVariantList entries = model->entries();
        QSignalSpy resets(model, &QAbstractItemModel::modelReset);
        QSignalSpy changes(model, &QAbstractItemModel::dataChanged);

        model->stage(model->indexOf(u"dpi"_s), 2000);
        model->setEntries(entries, true); // same keys: updated in place, edits kept
        QCOMPARE(resets.count(), 0);
        QVERIFY(changes.count() > 0);
        QVERIFY(model->hasChanges());

        model->setEntries(entries, false); // Reset
        QCOMPARE(resets.count(), 0);
        QVERIFY(!model->hasChanges());

        model->setEntries(entries.mid(1)); // other entries (another device): a real reset
        QCOMPARE(resets.count(), 1);
        QCOMPARE(model->count(), 3);
    }

    void errorsAndReadErrors()
    {
        QObject parent;
        StagedModel model(u"name"_s, {u"value"_s}, {u"readError=error"_s}, &parent);
        QVariantMap broken = setting(u"dpi"_s, QVariant::fromValue(nullptr));
        broken.insert(u"error"_s, u"device asleep"_s);
        model.setEntries({broken});
        const int readErrorRole = StagedModel::FirstFieldRole;
        QCOMPARE(model.roleNames().value(readErrorRole), QByteArray("readError"));
        QCOMPARE(model.data(model.index(0), readErrorRole).toString(), u"device asleep"_s);

        model.stage(0, 1000);
        model.setError(0, u"refused"_s);
        QVERIFY(model.hasErrors());
        QCOMPARE(model.writeError(0), u"refused"_s);
        model.stage(0, 1200); // editing again clears the error
        QVERIFY(!model.hasErrors());

        model.setLiveValue(u"dpi"_s, 1200); // a value arrived: readable now, and nothing left to apply
        QVERIFY(model.data(model.index(0), readErrorRole).isNull());
        QVERIFY(!model.hasChanges());
    }
};

QTEST_GUILESS_MAIN(StagedModelTest)

#include "stagedmodeltest.moc"
