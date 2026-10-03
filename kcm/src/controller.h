// SPDX-FileCopyrightText: 2026 plasmaar contributors
// SPDX-License-Identifier: GPL-2.0-or-later

#pragma once

#include <QDBusConnection>
#include <QObject>
#include <QVariant>
#include <qqmlregistration.h>

#include "plasmaarclient.h"
#include "stagedmodel.h"

/*
 * What the settings page shows and edits: the devices, the selected device's settings, button actions and
 * haptic events (each a StagedModel), the KDE actions to pick from, plus load/save/defaults with KCM
 * semantics. Independent of KCMUtils so that it can be tested against the mock service.
 */
class Controller : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    QML_UNCREATABLE("Provided by the KCM")

    Q_PROPERTY(ServiceState serviceState READ serviceState NOTIFY serviceStateChanged)
    Q_PROPERTY(bool ready READ isReady NOTIFY readyChanged)
    Q_PROPERTY(QVariantList devices READ devices NOTIFY devicesChanged)
    Q_PROPERTY(QString currentDeviceId READ currentDeviceId WRITE setCurrentDeviceId NOTIFY currentDeviceChanged)
    Q_PROPERTY(QVariantMap currentDevice READ currentDevice NOTIFY currentDeviceChanged)
    Q_PROPERTY(bool loading READ isLoading NOTIFY loadingChanged) // a newly selected device is loading
    Q_PROPERTY(bool saving READ isSaving NOTIFY savingChanged)
    Q_PROPERTY(StagedModel *settings READ settings CONSTANT)
    Q_PROPERTY(StagedModel *buttons READ buttons CONSTANT)
    Q_PROPERTY(StagedModel *hapticEvents READ hapticEvents CONSTANT)
    Q_PROPERTY(FeatureState settingsState READ settingsState NOTIFY featuresChanged)
    Q_PROPERTY(FeatureState buttonsState READ buttonsState NOTIFY featuresChanged)
    Q_PROPERTY(FeatureState hapticEventsState READ hapticEventsState NOTIFY featuresChanged)
    Q_PROPERTY(FeatureState kdeActionsState READ kdeActionsState NOTIFY featuresChanged)
    Q_PROPERTY(QString settingsError READ settingsError NOTIFY featuresChanged)
    Q_PROPERTY(QVariantList kdeActions READ kdeActions NOTIFY kdeActionsChanged)
    Q_PROPERTY(QStringList waveforms READ waveforms NOTIFY waveformsChanged)
    Q_PROPERTY(QString saveError READ saveError NOTIFY saveErrorChanged)
    Q_PROPERTY(QString notice READ notice NOTIFY noticeChanged)
    Q_PROPERTY(bool needsSave READ needsSave NOTIFY stagingChanged)
    Q_PROPERTY(bool hasDefaults READ hasDefaults NOTIFY stagingChanged)
    Q_PROPERTY(bool atDefaults READ atDefaults NOTIFY stagingChanged)
    Q_PROPERTY(QString snapshotPrefix READ snapshotPrefix CONSTANT)
    Q_PROPERTY(QString snapshotScenario READ snapshotScenario CONSTANT)

public:
    enum class ServiceState {
        Checking,
        Running,
        Missing,
    };
    Q_ENUM(ServiceState)

    enum class FeatureState {
        Loading,
        Available,
        Unavailable, // the device has nothing of the kind
        NeedsNewerService, // plasmaard does not have the method yet
        Failed,
    };
    Q_ENUM(FeatureState)

    explicit Controller(const QDBusConnection &bus = QDBusConnection::sessionBus(), QObject *parent = nullptr);

    ServiceState serviceState() const;
    bool isReady() const;
    QVariantList devices() const;
    QString currentDeviceId() const;
    void setCurrentDeviceId(const QString &deviceId);
    QVariantMap currentDevice() const;
    bool isLoading() const;
    bool isSaving() const;
    StagedModel *settings() const;
    StagedModel *buttons() const;
    StagedModel *hapticEvents() const;
    FeatureState settingsState() const;
    FeatureState buttonsState() const;
    FeatureState hapticEventsState() const;
    FeatureState kdeActionsState() const;
    QString settingsError() const;
    QVariantList kdeActions() const;
    QStringList waveforms() const;
    QString saveError() const;
    QString notice() const;
    bool needsSave() const;
    bool hasDefaults() const;
    bool atDefaults() const;
    QString snapshotPrefix() const;
    QString snapshotScenario() const;

    PlasmaarClient *client() const;

public Q_SLOTS:
    // KCM semantics: reload everything and drop staged edits (also the first load, which looks for the
    // service) / write staged edits / stage the defaults.
    void load();
    void save();
    void defaults();

    void playHaptic(const QString &waveform);
    void startService();
    void clearNotice();

public:
    // The localized label of a KDE action {component, action}, or a readable fallback.
    Q_INVOKABLE QString actionLabel(const QVariant &action) const;

    // Snapshot mode (PLASMAAR_KCM_SNAPSHOT): size and grab the top-level windows, then quit.
    Q_INVOKABLE void resizeTopLevelWindows(int width, int height) const;
    Q_INVOKABLE int topLevelWindowHeight() const;
    Q_INVOKABLE bool grabTopLevelWindow(const QString &path) const;
    Q_INVOKABLE void quitApplication() const;

Q_SIGNALS:
    void serviceStateChanged();
    void readyChanged();
    void devicesChanged();
    void currentDeviceChanged();
    void loadingChanged();
    void savingChanged();
    void featuresChanged();
    void kdeActionsChanged();
    void waveformsChanged();
    void saveErrorChanged();
    void noticeChanged();
    void stagingChanged();
    void saved(bool success);

private:
    struct Write {
        StagedModel *model;
        QString key;
        QString method;
        QVariantList args;
    };

    void onServiceStateChanged();
    void loadDevices();
    void loadDevice(bool keepStaged);
    void loadButtons(bool keepStaged);
    void loadKdeActions();
    void setDevices(const QVariantList &devices);
    void upsertDevice(const QVariantMap &device);
    void removeDevice(const QString &deviceId);
    void pickDevice();
    void setLoading(bool loading);
    void setSaving(bool saving);
    void setSaveError(const QString &error);
    void setNotice(const QString &notice);
    void runWrites(QList<Write> writes, QStringList failures);
    void applyWriteResult(const Write &write, const QVariant &result);
    QString describe(const PlasmaarClient::Error &error) const;
    FeatureState stateFor(const PlasmaarClient::Error &error) const;
    void updateReady();

    PlasmaarClient *m_client;
    StagedModel *m_settings;
    StagedModel *m_buttons;
    StagedModel *m_hapticEvents;
    QVariantList m_devices;
    QString m_currentDeviceId;
    bool m_devicesLoaded = false;
    int m_pending = 0; // replies still expected for the current device
    bool m_loading = false; // loading another device than the one shown
    QString m_loadedDeviceId;
    bool m_saving = false;
    bool m_ready = false;
    quint64 m_generation = 0; // bumped when switching devices, to drop stale replies
    FeatureState m_settingsState = FeatureState::Loading;
    FeatureState m_buttonsState = FeatureState::Loading;
    FeatureState m_hapticEventsState = FeatureState::Loading;
    FeatureState m_kdeActionsState = FeatureState::Loading;
    QString m_settingsError;
    QVariantList m_kdeActions;
    QHash<QString, QString> m_actionLabels; // "component/action" -> label
    QStringList m_eventWaveforms;
    QString m_saveError;
    QString m_notice;
    QString m_snapshotPrefix;
    QString m_snapshotScenario;
};
