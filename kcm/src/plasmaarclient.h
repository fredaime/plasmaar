// SPDX-FileCopyrightText: 2026 plasmaar contributors
// SPDX-License-Identifier: GPL-2.0-or-later

#pragma once

#include <QDBusConnection>
#include <QObject>
#include <QVariant>

#include <functional>

class QDBusMessage;
class QDBusServiceWatcher;

/*
 * Thin asynchronous client of the plasmaard D-Bus API (docs/dbus-api.md).
 *
 * Calls never block: each one is a QDBusPendingCallWatcher whose reply is parsed from JSON into a
 * QVariant and handed to a callback. Signals are relayed with their payloads parsed. The service may
 * come and go (it is a user service), which QDBusServiceWatcher tracks.
 */
class PlasmaarClient : public QObject
{
    Q_OBJECT

public:
    static const QString Service;
    static const QString Path;
    static const QString Interface;

    enum class ServiceState {
        Checking, // not known yet
        Running,
        Missing,
    };
    Q_ENUM(ServiceState)

    struct Error {
        QString name; // D-Bus error name; empty when the call succeeded
        QString message;

        bool isError() const
        {
            return !name.isEmpty();
        }
        bool isUnknownMethod() const; // an older plasmaard without this method
        bool isServiceGone() const; // nobody owns the bus name (anymore)
        QString shortName() const; // "NoSuchDevice", … for the plasmaard errors, else the full name
    };

    using Callback = std::function<void(const QVariant &result, const Error &error)>;

    explicit PlasmaarClient(const QDBusConnection &bus = QDBusConnection::sessionBus(), QObject *parent = nullptr);

    ServiceState serviceState() const;
    QString apiVersion() const;

    // Calls a method of the plasmaard interface. String arguments are passed as they are; use
    // Json::serialize for the *_json ones. The reply (a JSON string for most methods) is parsed; void
    // methods give an invalid QVariant. The callback is dropped if context is destroyed first.
    void call(const QString &method, const QVariantList &args, QObject *context, Callback callback);

    // Asks systemd --user to start plasmaard.service.
    void startService(QObject *context, Callback callback);

    // Checks whether the service is there; then followed automatically as it appears or vanishes.
    void checkService();

Q_SIGNALS:
    void serviceStateChanged();
    void deviceAdded(const QVariantMap &device);
    void deviceChanged(const QVariantMap &device);
    void deviceRemoved(const QString &deviceId);
    void settingChanged(const QString &deviceId, const QString &name, const QVariant &value);
    void buttonActionsChanged(const QString &deviceId);

private Q_SLOTS:
    void onDeviceAdded(const QString &json);
    void onDeviceChanged(const QString &json);
    void onDeviceRemoved(const QString &deviceId);
    void onSettingChanged(const QString &deviceId, const QString &name, const QString &valueJson);
    void onButtonActionsChanged(const QString &deviceId);

private:
    void setServiceState(ServiceState state);
    void dispatch(const QDBusMessage &message, QObject *context, Callback callback);

    QDBusConnection m_bus;
    QDBusServiceWatcher *m_watcher;
    ServiceState m_state = ServiceState::Checking;
    QString m_apiVersion;
    quint64 m_checkGeneration = 0;
};
