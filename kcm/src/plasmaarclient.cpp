// SPDX-FileCopyrightText: 2026 plasmaar contributors
// SPDX-License-Identifier: GPL-2.0-or-later

#include "plasmaarclient.h"

#include "json.h"

#include <QDBusMessage>
#include <QDBusPendingCallWatcher>
#include <QDBusPendingReply>
#include <QDBusServiceWatcher>
#include <QLoggingCategory>
#include <QPointer>

Q_LOGGING_CATEGORY(KCM_PLASMAAR, "kcm_plasmaar", QtWarningMsg)

const QString PlasmaarClient::Service = QStringLiteral("io.github.fredaime.Plasmaar");
const QString PlasmaarClient::Path = QStringLiteral("/io/github/fredaime/Plasmaar");
const QString PlasmaarClient::Interface = QStringLiteral("io.github.fredaime.Plasmaar1");

namespace
{
// Device calls can take seconds while a Bluetooth device wakes up; plasmaard answers or fails on its own.
constexpr int CallTimeoutMs = 30000;
}

bool PlasmaarClient::Error::isUnknownMethod() const
{
    return name == QLatin1String("org.freedesktop.DBus.Error.UnknownMethod");
}

bool PlasmaarClient::Error::isServiceGone() const
{
    return name == QLatin1String("org.freedesktop.DBus.Error.ServiceUnknown") || name == QLatin1String("org.freedesktop.DBus.Error.NameHasNoOwner")
        || name == QLatin1String("org.freedesktop.DBus.Error.Disconnected");
}

QString PlasmaarClient::Error::shortName() const
{
    const QString prefix = Interface + QLatin1String(".Error.");
    return name.startsWith(prefix) ? name.mid(prefix.size()) : name;
}

PlasmaarClient::PlasmaarClient(const QDBusConnection &bus, QObject *parent)
    : QObject(parent)
    , m_bus(bus)
    , m_watcher(new QDBusServiceWatcher(Service, bus, QDBusServiceWatcher::WatchForOwnerChange, this))
{
    connect(m_watcher, &QDBusServiceWatcher::serviceRegistered, this, &PlasmaarClient::checkService);
    connect(m_watcher, &QDBusServiceWatcher::serviceUnregistered, this, [this] {
        ++m_checkGeneration;
        setServiceState(ServiceState::Missing);
    });

    // QtDBus follows the owner of the well-known name, so these survive service restarts.
    const struct {
        const char *signal;
        const char *slot;
    } relays[] = {
        {"DeviceAdded", SLOT(onDeviceAdded(QString))},
        {"DeviceChanged", SLOT(onDeviceChanged(QString))},
        {"DeviceRemoved", SLOT(onDeviceRemoved(QString))},
        {"SettingChanged", SLOT(onSettingChanged(QString, QString, QString))},
        {"ButtonActionsChanged", SLOT(onButtonActionsChanged(QString))},
    };
    for (const auto &relay : relays) {
        if (!m_bus.connect(Service, Path, Interface, QString::fromLatin1(relay.signal), this, relay.slot)) {
            qCWarning(KCM_PLASMAAR) << "cannot listen to" << relay.signal << m_bus.lastError().message();
        }
    }
}

PlasmaarClient::ServiceState PlasmaarClient::serviceState() const
{
    return m_state;
}

QString PlasmaarClient::apiVersion() const
{
    return m_apiVersion;
}

void PlasmaarClient::setServiceState(ServiceState state)
{
    if (m_state != state) {
        m_state = state;
        Q_EMIT serviceStateChanged();
    }
}

void PlasmaarClient::checkService()
{
    const quint64 generation = ++m_checkGeneration;
    call(QStringLiteral("GetVersion"), {}, this, [this, generation](const QVariant &result, const Error &error) {
        if (generation != m_checkGeneration) {
            return; // a newer check or an unregistration overtook this one
        }
        if (error.isError()) {
            qCDebug(KCM_PLASMAAR) << "plasmaard not available:" << error.name << error.message;
            setServiceState(ServiceState::Missing);
            return;
        }
        m_apiVersion = result.toString();
        setServiceState(ServiceState::Running);
    });
}

void PlasmaarClient::call(const QString &method, const QVariantList &args, QObject *context, Callback callback)
{
    QDBusMessage message = QDBusMessage::createMethodCall(Service, Path, Interface, method);
    message.setArguments(args);
    dispatch(message, context, std::move(callback));
}

void PlasmaarClient::startService(QObject *context, Callback callback)
{
    QDBusMessage message = QDBusMessage::createMethodCall(QStringLiteral("org.freedesktop.systemd1"),
                                                          QStringLiteral("/org/freedesktop/systemd1"),
                                                          QStringLiteral("org.freedesktop.systemd1.Manager"),
                                                          QStringLiteral("StartUnit"));
    message.setArguments({QStringLiteral("plasmaard.service"), QStringLiteral("replace")});
    dispatch(message, context, std::move(callback));
}

void PlasmaarClient::dispatch(const QDBusMessage &message, QObject *context, Callback callback)
{
    auto *watcher = new QDBusPendingCallWatcher(m_bus.asyncCall(message, CallTimeoutMs), this);
    QPointer<QObject> guard(context);
    const QString method = message.member();
    connect(watcher, &QDBusPendingCallWatcher::finished, this, [guard, method, callback = std::move(callback)](QDBusPendingCallWatcher *call) {
        call->deleteLater();
        if (!guard) {
            return;
        }
        const QDBusMessage reply = call->reply();
        if (reply.type() == QDBusMessage::ErrorMessage) {
            qCDebug(KCM_PLASMAAR) << method << "failed:" << reply.errorName() << reply.errorMessage();
            callback(QVariant(), Error{reply.errorName(), reply.errorMessage()});
            return;
        }
        QVariant result;
        if (!reply.arguments().isEmpty()) {
            const QVariant first = reply.arguments().constFirst();
            if (first.typeId() == QMetaType::QString) {
                bool ok = false;
                result = Json::parse(first.toString(), &ok);
                if (!ok) {
                    result = first; // GetVersion and other plain strings
                }
            } else {
                result = first;
            }
        }
        callback(result, Error{});
    });
}

void PlasmaarClient::onDeviceAdded(const QString &json)
{
    Q_EMIT deviceAdded(Json::parse(json).toMap());
}

void PlasmaarClient::onDeviceChanged(const QString &json)
{
    Q_EMIT deviceChanged(Json::parse(json).toMap());
}

void PlasmaarClient::onDeviceRemoved(const QString &deviceId)
{
    Q_EMIT deviceRemoved(deviceId);
}

void PlasmaarClient::onSettingChanged(const QString &deviceId, const QString &name, const QString &valueJson)
{
    Q_EMIT settingChanged(deviceId, name, Json::parse(valueJson));
}

void PlasmaarClient::onButtonActionsChanged(const QString &deviceId)
{
    Q_EMIT buttonActionsChanged(deviceId);
}

#include "moc_plasmaarclient.cpp"
