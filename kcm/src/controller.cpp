// SPDX-FileCopyrightText: 2026 plasmaar contributors
// SPDX-License-Identifier: GPL-2.0-or-later

#include "controller.h"

#include "json.h"

#include <KLocalizedString>

#include <QCoreApplication>
#include <QGuiApplication>
#include <QJSValue>
#include <QPixmap>
#include <QScreen>
#include <QWindow>

namespace
{
const QString MapChoice = QStringLiteral("MAP_CHOICE");

QVariantMap toMap(const QVariant &value)
{
    if (value.metaType() == QMetaType::fromType<QJSValue>()) {
        return value.value<QJSValue>().toVariant().toMap();
    }
    return value.toMap();
}
}

Controller::Controller(const QDBusConnection &bus, QObject *parent)
    : QObject(parent)
    , m_client(new PlasmaarClient(bus, this))
    , m_settings(new StagedModel(QStringLiteral("name"),
                                 {QStringLiteral("value")},
                                 {QStringLiteral("name"),
                                  QStringLiteral("label"),
                                  QStringLiteral("description"),
                                  QStringLiteral("kind"),
                                  QStringLiteral("display"),
                                  QStringLiteral("writable"),
                                  QStringLiteral("choices"),
                                  QStringLiteral("min"),
                                  QStringLiteral("max"),
                                  QStringLiteral("keys"),
                                  QStringLiteral("readError=error")},
                                 this))
    , m_buttons(new StagedModel(QStringLiteral("control"),
                                {QStringLiteral("mode"), QStringLiteral("press"), QStringLiteral("gestures")},
                                {QStringLiteral("control"), QStringLiteral("name"), QStringLiteral("modes")},
                                this))
    , m_hapticEvents(new StagedModel(QStringLiteral("event"), {QStringLiteral("waveform")}, {QStringLiteral("event"), QStringLiteral("label")}, this))
    , m_snapshotPrefix(qEnvironmentVariable("PLASMAAR_KCM_SNAPSHOT"))
    , m_snapshotScenario(qEnvironmentVariable("PLASMAAR_KCM_SNAPSHOT_SCENARIO"))
{
    for (StagedModel *model : {m_settings, m_buttons, m_hapticEvents}) {
        connect(model, &StagedModel::stateChanged, this, &Controller::stagingChanged);
    }
    connect(m_settings, &StagedModel::stateChanged, this, [this] {
        if (m_eventWaveforms.isEmpty()) {
            Q_EMIT waveformsChanged(); // they come from the haptic-play setting then
        }
    });
    connect(m_client, &PlasmaarClient::serviceStateChanged, this, &Controller::onServiceStateChanged);
    connect(m_client, &PlasmaarClient::deviceAdded, this, &Controller::upsertDevice);
    connect(m_client, &PlasmaarClient::deviceChanged, this, &Controller::upsertDevice);
    connect(m_client, &PlasmaarClient::deviceRemoved, this, &Controller::removeDevice);
    connect(m_client, &PlasmaarClient::settingChanged, this, [this](const QString &deviceId, const QString &name, const QVariant &value) {
        if (deviceId == m_currentDeviceId) {
            m_settings->setLiveValue(name, value);
        }
    });
    connect(m_client, &PlasmaarClient::buttonActionsChanged, this, [this](const QString &deviceId) {
        if (deviceId == m_currentDeviceId && m_buttonsState == FeatureState::Available) {
            loadButtons(true);
        }
    });
}

QString Controller::snapshotScenario() const
{
    return m_snapshotScenario;
}

PlasmaarClient *Controller::client() const
{
    return m_client;
}

Controller::ServiceState Controller::serviceState() const
{
    switch (m_client->serviceState()) {
    case PlasmaarClient::ServiceState::Running:
        return ServiceState::Running;
    case PlasmaarClient::ServiceState::Missing:
        return ServiceState::Missing;
    case PlasmaarClient::ServiceState::Checking:
        break;
    }
    return ServiceState::Checking;
}

bool Controller::isReady() const
{
    return m_ready;
}

void Controller::updateReady()
{
    const ServiceState state = serviceState();
    const bool ready = state == ServiceState::Missing
        || (state == ServiceState::Running && m_devicesLoaded && m_pending == 0 && m_kdeActionsState != FeatureState::Loading);
    if (ready != m_ready) {
        m_ready = ready;
        Q_EMIT readyChanged();
    }
}

QVariantList Controller::devices() const
{
    return m_devices;
}

QString Controller::currentDeviceId() const
{
    return m_currentDeviceId;
}

void Controller::setCurrentDeviceId(const QString &deviceId)
{
    if (deviceId == m_currentDeviceId) {
        return;
    }
    m_currentDeviceId = deviceId;
    Q_EMIT currentDeviceChanged();
    loadDevice(false);
}

QVariantMap Controller::currentDevice() const
{
    for (const QVariant &device : m_devices) {
        if (device.toMap().value(QStringLiteral("id")).toString() == m_currentDeviceId) {
            return device.toMap();
        }
    }
    return {};
}

bool Controller::isLoading() const
{
    return m_loading;
}

void Controller::setLoading(bool loading)
{
    if (m_loading != loading) {
        m_loading = loading;
        Q_EMIT loadingChanged();
    }
}

bool Controller::isSaving() const
{
    return m_saving;
}

StagedModel *Controller::settings() const
{
    return m_settings;
}

StagedModel *Controller::buttons() const
{
    return m_buttons;
}

StagedModel *Controller::hapticEvents() const
{
    return m_hapticEvents;
}

Controller::FeatureState Controller::settingsState() const
{
    return m_settingsState;
}

Controller::FeatureState Controller::buttonsState() const
{
    return m_buttonsState;
}

Controller::FeatureState Controller::hapticEventsState() const
{
    return m_hapticEventsState;
}

Controller::FeatureState Controller::kdeActionsState() const
{
    return m_kdeActionsState;
}

QString Controller::settingsError() const
{
    return m_settingsError;
}

QVariantList Controller::kdeActions() const
{
    return m_kdeActions;
}

QStringList Controller::waveforms() const
{
    if (!m_eventWaveforms.isEmpty()) {
        return m_eventWaveforms;
    }
    QStringList names;
    const QVariantMap play = m_settings->get(m_settings->indexOf(QStringLiteral("haptic-play")));
    const QVariantList choices = play.value(QStringLiteral("choices")).toList();
    for (const QVariant &choice : choices) {
        names.append(choice.toMap().value(QStringLiteral("name")).toString());
    }
    return names;
}

QString Controller::saveError() const
{
    return m_saveError;
}

QString Controller::notice() const
{
    return m_notice;
}

bool Controller::needsSave() const
{
    return m_settings->hasChanges() || m_buttons->hasChanges() || m_hapticEvents->hasChanges();
}

bool Controller::hasDefaults() const
{
    return m_settings->hasDefaults();
}

bool Controller::atDefaults() const
{
    return m_settings->atDefaults();
}

QString Controller::snapshotPrefix() const
{
    return m_snapshotPrefix;
}

// --- loading ---

void Controller::onServiceStateChanged()
{
    Q_EMIT serviceStateChanged(); // first: the page drops its views before the models are emptied
    if (m_client->serviceState() == PlasmaarClient::ServiceState::Running) {
        loadDevices();
        loadKdeActions();
    } else {
        ++m_generation;
        m_pending = 0;
        m_loadedDeviceId.clear();
        setLoading(false);
        m_devicesLoaded = false;
        m_devices.clear();
        Q_EMIT devicesChanged();
        m_settings->setEntries({});
        m_buttons->setEntries({});
        m_hapticEvents->setEntries({});
        m_eventWaveforms.clear();
        Q_EMIT waveformsChanged();
    }
    updateReady();
}

void Controller::load()
{
    m_settings->discard();
    m_buttons->discard();
    m_hapticEvents->discard();
    setSaveError(QString());
    setNotice(QString());
    if (m_client->serviceState() == PlasmaarClient::ServiceState::Running) {
        loadDevices();
    } else {
        m_client->checkService();
    }
}

void Controller::loadDevices()
{
    m_client->call(QStringLiteral("ListDevices"), {}, this, [this](const QVariant &result, const PlasmaarClient::Error &error) {
        m_devicesLoaded = true;
        if (error.isError()) {
            m_settingsError = describe(error);
            setDevices({});
        } else {
            setDevices(result.toList());
        }
        updateReady();
    });
}

void Controller::setDevices(const QVariantList &devices)
{
    m_devices = devices;
    Q_EMIT devicesChanged();
    if (currentDevice().isEmpty()) {
        pickDevice();
    } else {
        Q_EMIT currentDeviceChanged();
        loadDevice(false);
    }
}

void Controller::pickDevice()
{
    // the first online device, else the first one
    QString first;
    QString firstOnline;
    for (const QVariant &device : std::as_const(m_devices)) {
        const QVariantMap map = device.toMap();
        const QString id = map.value(QStringLiteral("id")).toString();
        if (first.isEmpty()) {
            first = id;
        }
        if (firstOnline.isEmpty() && map.value(QStringLiteral("online")).toBool()) {
            firstOnline = id;
        }
    }
    m_currentDeviceId = firstOnline.isEmpty() ? first : firstOnline;
    Q_EMIT currentDeviceChanged();
    loadDevice(false);
}

void Controller::upsertDevice(const QVariantMap &device)
{
    const QString id = device.value(QStringLiteral("id")).toString();
    if (id.isEmpty()) {
        return;
    }
    bool cameOnline = false;
    bool found = false;
    for (QVariant &existing : m_devices) {
        if (existing.toMap().value(QStringLiteral("id")).toString() == id) {
            cameOnline = !existing.toMap().value(QStringLiteral("online")).toBool() && device.value(QStringLiteral("online")).toBool();
            existing = device;
            found = true;
            break;
        }
    }
    if (!found) {
        m_devices.append(device);
    }
    Q_EMIT devicesChanged();
    if (m_currentDeviceId.isEmpty()) {
        pickDevice();
    } else if (id == m_currentDeviceId) {
        Q_EMIT currentDeviceChanged();
        if (cameOnline) {
            loadDevice(true); // values that could not be read while it was away
        }
    }
}

void Controller::removeDevice(const QString &deviceId)
{
    for (qsizetype i = 0; i < m_devices.size(); ++i) {
        if (m_devices.at(i).toMap().value(QStringLiteral("id")).toString() == deviceId) {
            m_devices.removeAt(i);
            Q_EMIT devicesChanged();
            break;
        }
    }
    if (deviceId == m_currentDeviceId) {
        pickDevice();
    }
}

void Controller::loadDevice(bool keepStaged)
{
    const quint64 generation = ++m_generation;
    const QString id = m_currentDeviceId;
    // Another device: the page drops its views first (loading), then the models are emptied. The same
    // device again (Reset, reconnection): the models are updated in place when the data arrives.
    const bool switching = id != m_loadedDeviceId;
    m_loadedDeviceId = id;
    if (switching) {
        setLoading(true);
        m_settings->setEntries({});
        m_buttons->setEntries({});
        m_hapticEvents->setEntries({});
        m_eventWaveforms.clear();
        Q_EMIT waveformsChanged();
        m_settingsState = m_buttonsState = m_hapticEventsState = FeatureState::Loading;
        m_settingsError.clear();
        Q_EMIT featuresChanged();
    }
    if (id.isEmpty()) {
        m_pending = 0;
        m_settingsState = m_buttonsState = m_hapticEventsState = FeatureState::Unavailable;
        Q_EMIT featuresChanged();
        setLoading(false);
        updateReady();
        return;
    }
    m_pending = 3;
    updateReady();

    auto done = [this, generation] {
        if (generation == m_generation && m_pending > 0 && --m_pending == 0) {
            setLoading(false);
            updateReady();
        }
    };

    m_client->call(QStringLiteral("ListSettings"), {id}, this, [=, this](const QVariant &result, const PlasmaarClient::Error &error) {
        if (generation != m_generation) {
            return;
        }
        if (error.isError()) {
            m_settings->setEntries({});
            m_settingsState = stateFor(error) == FeatureState::Unavailable ? FeatureState::Unavailable : FeatureState::Failed;
            m_settingsError = describe(error);
        } else {
            m_settings->setEntries(result.toList(), keepStaged);
            m_settingsState = m_settings->count() > 0 ? FeatureState::Available : FeatureState::Unavailable;
            m_settingsError.clear();
        }
        Q_EMIT featuresChanged();
        Q_EMIT waveformsChanged();
        done();
    });

    m_client->call(QStringLiteral("GetButtonActions"), {id}, this, [=, this](const QVariant &result, const PlasmaarClient::Error &error) {
        if (generation != m_generation) {
            return;
        }
        if (error.isError()) {
            m_buttons->setEntries({});
            m_buttonsState = stateFor(error);
        } else {
            m_buttons->setEntries(result.toMap().value(QStringLiteral("buttons")).toList(), keepStaged);
            m_buttonsState = m_buttons->count() > 0 ? FeatureState::Available : FeatureState::Unavailable;
        }
        Q_EMIT featuresChanged();
        done();
    });

    m_client->call(QStringLiteral("GetHapticEvents"), {id}, this, [=, this](const QVariant &result, const PlasmaarClient::Error &error) {
        if (generation != m_generation) {
            return;
        }
        if (error.isError()) {
            m_hapticEvents->setEntries({});
            m_eventWaveforms.clear();
            m_hapticEventsState = stateFor(error);
        } else {
            const QVariantMap map = result.toMap();
            m_eventWaveforms = map.value(QStringLiteral("waveforms")).toStringList();
            m_hapticEvents->setEntries(map.value(QStringLiteral("events")).toList(), keepStaged);
            m_hapticEventsState = m_hapticEvents->count() > 0 ? FeatureState::Available : FeatureState::Unavailable;
        }
        Q_EMIT featuresChanged();
        Q_EMIT waveformsChanged();
        done();
    });
}

void Controller::loadButtons(bool keepStaged)
{
    const quint64 generation = m_generation;
    m_client->call(QStringLiteral("GetButtonActions"), {m_currentDeviceId}, this, [=, this](const QVariant &result, const PlasmaarClient::Error &error) {
        if (generation != m_generation || error.isError()) {
            return;
        }
        m_buttons->setEntries(result.toMap().value(QStringLiteral("buttons")).toList(), keepStaged);
    });
}

void Controller::loadKdeActions()
{
    m_kdeActionsState = FeatureState::Loading;
    Q_EMIT featuresChanged();
    m_client->call(QStringLiteral("ListKdeActions"), {}, this, [this](const QVariant &result, const PlasmaarClient::Error &error) {
        m_kdeActions = error.isError() ? QVariantList() : result.toList();
        m_actionLabels.clear();
        for (const QVariant &component : std::as_const(m_kdeActions)) {
            const QVariantMap map = component.toMap();
            const QString name = map.value(QStringLiteral("component")).toString();
            const QVariantList actions = map.value(QStringLiteral("actions")).toList();
            for (const QVariant &action : actions) {
                const QVariantMap actionMap = action.toMap();
                m_actionLabels.insert(name + QLatin1Char('/') + actionMap.value(QStringLiteral("name")).toString(),
                                      actionMap.value(QStringLiteral("label")).toString());
            }
        }
        m_kdeActionsState = error.isError() ? stateFor(error) : FeatureState::Available;
        Q_EMIT kdeActionsChanged();
        Q_EMIT featuresChanged();
        updateReady();
    });
}

Controller::FeatureState Controller::stateFor(const PlasmaarClient::Error &error) const
{
    if (error.isUnknownMethod()) {
        return FeatureState::NeedsNewerService;
    }
    const QString name = error.shortName();
    if (name == QLatin1String("NotSupported") || name == QLatin1String("NoSuchDevice")) {
        return FeatureState::Unavailable;
    }
    return FeatureState::Failed;
}

QString Controller::describe(const PlasmaarClient::Error &error) const
{
    const QString name = error.shortName();
    if (name == QLatin1String("DeviceOffline")) {
        return i18n("The device is switched off, asleep or out of range.");
    }
    if (name == QLatin1String("NoSuchDevice")) {
        return i18n("The device is no longer connected.");
    }
    if (name == QLatin1String("NoSuchSetting")) {
        return i18n("The device no longer has this setting.");
    }
    if (name == QLatin1String("InvalidValue")) {
        return i18n("The value was refused: %1", error.message);
    }
    if (name == QLatin1String("NotSupported")) {
        return i18n("The device does not support this.");
    }
    if (error.isServiceGone()) {
        return i18n("The plasmaard service is not running.");
    }
    if (error.name == QLatin1String("org.freedesktop.DBus.Error.NoReply") || error.name == QLatin1String("org.freedesktop.DBus.Error.Timeout")) {
        return i18n("The plasmaard service did not answer in time.");
    }
    return error.message.isEmpty() ? error.name : error.message;
}

// --- saving ---

void Controller::save()
{
    if (m_saving) {
        return;
    }
    const QString id = m_currentDeviceId;
    QList<Write> writes;
    // Settings first: a button action written afterwards decides the button's final diversion.
    const auto settingChanges = m_settings->changes();
    for (const StagedModel::Change &change : settingChanges) {
        if (change.entry.value(QStringLiteral("kind")).toString() == MapChoice) {
            const QVariantMap pending = change.pending.toMap();
            for (const QString &key : change.changedKeys) {
                writes.append({m_settings, change.key, QStringLiteral("SetSettingKey"), {id, change.key, key, Json::serialize(pending.value(key))}});
            }
        } else {
            writes.append({m_settings, change.key, QStringLiteral("SetSetting"), {id, change.key, Json::serialize(change.pending)}});
        }
    }
    const auto buttonChanges = m_buttons->changes();
    for (const StagedModel::Change &change : buttonChanges) {
        writes.append({m_buttons,
                       change.key,
                       QStringLiteral("SetButtonAction"),
                       {id, change.entry.value(QStringLiteral("control")).toInt(), Json::serialize(change.pending)}});
    }
    const auto eventChanges = m_hapticEvents->changes();
    for (const StagedModel::Change &change : eventChanges) {
        const QString waveform = change.pending.isNull() ? QString() : change.pending.toString();
        writes.append({m_hapticEvents, change.key, QStringLiteral("SetHapticEvent"), {id, change.key, waveform}});
    }
    m_settings->clearErrors();
    m_buttons->clearErrors();
    m_hapticEvents->clearErrors();
    setSaveError(QString());
    if (writes.isEmpty()) {
        Q_EMIT saved(true);
        return;
    }
    setSaving(true);
    runWrites(writes, {});
}

void Controller::runWrites(QList<Write> writes, QStringList failures)
{
    if (writes.isEmpty()) {
        setSaving(false);
        if (!failures.isEmpty()) {
            setSaveError(i18np("One change could not be applied:", "%1 changes could not be applied:", failures.size()) + QLatin1Char('\n')
                         + failures.join(QLatin1Char('\n')));
        }
        Q_EMIT saved(failures.isEmpty());
        return;
    }
    const Write write = writes.takeFirst();
    const quint64 generation = m_generation;
    write.model->setBusy(write.model->indexOf(write.key), true);
    m_client->call(write.method, write.args, this, [=, this](const QVariant &result, const PlasmaarClient::Error &error) mutable {
        if (generation == m_generation) {
            const int row = write.model->indexOf(write.key);
            write.model->setBusy(row, false);
            if (error.isError()) {
                const QString message = describe(error);
                write.model->setError(row, message);
                const QVariantMap entry = write.model->get(row);
                const QString label = entry.value(QStringLiteral("label"), entry.value(QStringLiteral("name"), write.key)).toString();
                failures.append(i18nc("@info failed write: setting label, error message", "%1: %2", label, message));
            } else {
                applyWriteResult(write, result);
            }
        }
        runWrites(writes, failures);
    });
}

void Controller::applyWriteResult(const Write &write, const QVariant &result)
{
    if (write.model == m_settings) {
        m_settings->setLiveValue(write.key, result);
        return;
    }
    const QVariantMap map = result.toMap();
    const int row = write.model->indexOf(write.key);
    if (write.model == m_hapticEvents && map.contains(QStringLiteral("events"))) {
        m_hapticEvents->setEntries(map.value(QStringLiteral("events")).toList(), true);
    } else if (!map.isEmpty() && map.contains(write.model == m_buttons ? QStringLiteral("control") : QStringLiteral("event"))) {
        write.model->setLiveEntry(map);
    } else {
        // no description in the reply: what was written is now the live value
        write.model->setLiveValue(write.key, write.model->pendingValue(row));
    }
}

void Controller::defaults()
{
    m_settings->stageDefaults();
}

void Controller::setSaving(bool saving)
{
    if (m_saving != saving) {
        m_saving = saving;
        Q_EMIT savingChanged();
    }
}

void Controller::setSaveError(const QString &error)
{
    if (m_saveError != error) {
        m_saveError = error;
        Q_EMIT saveErrorChanged();
    }
}

void Controller::setNotice(const QString &notice)
{
    if (m_notice != notice) {
        m_notice = notice;
        Q_EMIT noticeChanged();
    }
}

void Controller::clearNotice()
{
    setNotice(QString());
}

// --- immediate actions ---

void Controller::playHaptic(const QString &waveform)
{
    m_client->call(QStringLiteral("PlayHaptic"), {m_currentDeviceId, waveform}, this, [this](const QVariant &, const PlasmaarClient::Error &error) {
        if (error.isError()) {
            setNotice(i18n("Could not play the effect: %1", describe(error)));
        }
    });
}

void Controller::startService()
{
    setNotice(QString());
    m_client->startService(this, [this](const QVariant &, const PlasmaarClient::Error &error) {
        if (error.isError()) {
            setNotice(i18n("Could not start plasmaard: %1", error.message.isEmpty() ? error.name : error.message));
        }
    });
}

QString Controller::actionLabel(const QVariant &action) const
{
    const QVariantMap map = toMap(action);
    const QString component = map.value(QStringLiteral("component")).toString();
    const QString name = map.value(QStringLiteral("action")).toString();
    if (component.isEmpty() || name.isEmpty()) {
        return QString();
    }
    const QString label = m_actionLabels.value(component + QLatin1Char('/') + name);
    if (!label.isEmpty()) {
        return label;
    }
    return i18nc("@label a KDE action that is not in the list: action name, component", "%1 (%2)", name, component);
}

// --- snapshot mode ---

void Controller::resizeTopLevelWindows(int width, int height) const
{
    const auto windows = QGuiApplication::topLevelWindows();
    for (QWindow *window : windows) {
        if (window->isVisible() && (window->type() == Qt::Window || window->type() == Qt::Dialog)) {
            window->resize(width, height);
        }
    }
}

static QWindow *largestTopLevelWindow()
{
    QWindow *largest = nullptr;
    const auto windows = QGuiApplication::topLevelWindows();
    for (QWindow *window : windows) {
        if (window->isVisible() && (!largest || window->width() * window->height() > largest->width() * largest->height())) {
            largest = window;
        }
    }
    return largest;
}

int Controller::topLevelWindowHeight() const
{
    QWindow *window = largestTopLevelWindow();
    return window ? window->height() : 0;
}

bool Controller::grabTopLevelWindow(const QString &path) const
{
    QWindow *largest = largestTopLevelWindow();
    if (!largest || !largest->screen()) {
        return false;
    }
    const QPixmap pixmap = largest->screen()->grabWindow(largest->winId());
    return !pixmap.isNull() && pixmap.save(path);
}

void Controller::quitApplication() const
{
    QMetaObject::invokeMethod(QCoreApplication::instance(), &QCoreApplication::quit, Qt::QueuedConnection);
}

#include "moc_controller.cpp"
