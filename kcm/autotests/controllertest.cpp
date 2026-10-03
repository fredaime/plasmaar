// SPDX-FileCopyrightText: 2026 plasmaar contributors
// SPDX-License-Identifier: GPL-2.0-or-later

// The Controller (and its D-Bus client) against tools/mock_plasmaard.py on a private session bus.
// Run through ctest, which wraps it in dbus-run-session; it refuses to run next to a real plasmaard.

#include "controller.h"
#include "json.h"

#include <QDBusConnection>
#include <QDBusConnectionInterface>
#include <QDBusInterface>
#include <QDBusReply>
#include <QProcess>
#include <QSignalSpy>
#include <QTest>

using namespace Qt::StringLiterals;

namespace
{
const QString MX4 = u"B04200000000-BD2BC136"_s;
const QString K850 = u"B34D40620000-FF883310"_s;
const QString MockInterface = u"io.github.fredaime.PlasmaarMock"_s;
constexpr int Timeout = 10000;

QVariantMap action(const QString &component, const QString &name)
{
    return {{u"component"_s, component}, {u"action"_s, name}};
}
}

class ControllerTest : public QObject
{
    Q_OBJECT

private:
    QProcess *m_mock = nullptr;

    void startMock(const QStringList &extraArgs = {})
    {
        m_mock = new QProcess(this);
        m_mock->setProcessChannelMode(QProcess::ForwardedChannels);
        QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
        env.insert(u"LANGUAGE"_s, u"fr"_s);
        m_mock->setProcessEnvironment(env);
        m_mock->start(qEnvironmentVariable("PLASMAAR_PYTHON", u"python3"_s), QStringList{qEnvironmentVariable("PLASMAAR_MOCK")} + extraArgs);
        QVERIFY2(m_mock->waitForStarted(), "cannot start the mock service");
        QTRY_VERIFY_WITH_TIMEOUT(QDBusConnection::sessionBus().interface()->isServiceRegistered(PlasmaarClient::Service), Timeout);
        // make sure that this is the mock, never a real plasmaard
        QDBusInterface introspect(PlasmaarClient::Service, PlasmaarClient::Path, u"org.freedesktop.DBus.Introspectable"_s);
        const QDBusReply<QString> xml = introspect.call(u"Introspect"_s);
        QVERIFY2(xml.isValid() && xml.value().contains(MockInterface), "the service on this bus is not the mock");
    }

    void stopMock()
    {
        if (!m_mock) {
            return;
        }
        if (m_mock->state() != QProcess::NotRunning) {
            m_mock->terminate();
            if (!m_mock->waitForFinished(5000)) {
                m_mock->kill();
                m_mock->waitForFinished();
            }
        }
        delete m_mock;
        m_mock = nullptr;
        QTRY_VERIFY_WITH_TIMEOUT(!QDBusConnection::sessionBus().interface()->isServiceRegistered(PlasmaarClient::Service), Timeout);
    }

    // synchronous calls are fine in a test
    QVariant api(const QString &method, const QVariantList &args)
    {
        QDBusInterface iface(PlasmaarClient::Service, PlasmaarClient::Path, PlasmaarClient::Interface);
        const QDBusMessage reply = iface.callWithArgumentList(QDBus::Block, method, args);
        if (reply.type() != QDBusMessage::ReplyMessage || reply.arguments().isEmpty()) {
            return {};
        }
        return Json::parse(reply.arguments().constFirst().toString());
    }

    void mock(const QString &method, const QVariantList &args)
    {
        QDBusInterface iface(PlasmaarClient::Service, PlasmaarClient::Path, MockInterface);
        const QDBusMessage reply = iface.callWithArgumentList(QDBus::Block, method, args);
        QVERIFY2(reply.type() == QDBusMessage::ReplyMessage, qPrintable(reply.errorMessage()));
    }

    QVariant deviceSetting(const QString &deviceId, const QString &name)
    {
        const QVariantList settings = api(u"ListSettings"_s, {deviceId}).toList();
        for (const QVariant &setting : settings) {
            if (setting.toMap().value(u"name"_s) == name) {
                return setting.toMap().value(u"value"_s);
            }
        }
        return {};
    }

    QVariantMap deviceButton(const QString &deviceId, int control)
    {
        const QVariantList buttons = api(u"GetButtonActions"_s, {deviceId}).toMap().value(u"buttons"_s).toList();
        for (const QVariant &button : buttons) {
            if (button.toMap().value(u"control"_s).toInt() == control) {
                return button.toMap();
            }
        }
        return {};
    }

    static bool save(Controller &controller, bool expected = true)
    {
        QSignalSpy saved(&controller, &Controller::saved);
        controller.save();
        if (!saved.wait(Timeout)) {
            return false;
        }
        return saved.first().first().toBool() == expected;
    }

private Q_SLOTS:
    void initTestCase()
    {
        QVERIFY2(!qEnvironmentVariableIsEmpty("PLASMAAR_MOCK"), "PLASMAAR_MOCK must point to tools/mock_plasmaard.py (run through ctest)");
        QVERIFY2(!QDBusConnection::sessionBus().interface()->isServiceRegistered(PlasmaarClient::Service),
                 "a plasmaard already runs on this bus: refusing to test against it (run through ctest, which uses a private bus)");
    }

    void init()
    {
        const QString test = QString::fromLatin1(QTest::currentTestFunction());
        if (test == u"degradesWithAnOlderService"_s) {
            startMock({u"--legacy"_s});
        } else if (test == u"reportsWriteErrors"_s) {
            startMock({u"--fail"_s, u"smart-shift"_s, u"--fail"_s, u"button:416"_s});
        } else {
            startMock();
        }
    }

    void cleanup()
    {
        stopMock();
    }

    void loadsDevicesAndSettings()
    {
        Controller controller;
        controller.load(); // as the KCM host does
        QTRY_VERIFY_WITH_TIMEOUT(controller.isReady(), Timeout);
        QCOMPARE(controller.serviceState(), Controller::ServiceState::Running);
        QCOMPARE(controller.devices().size(), 3);
        QCOMPARE(controller.currentDeviceId(), MX4); // the first online device
        QCOMPARE(controller.currentDevice().value(u"name"_s).toString(), u"MX Master 4"_s);
        QCOMPARE(controller.settings()->count(), 15);
        QCOMPARE(controller.settingsState(), Controller::FeatureState::Available);
        QCOMPARE(controller.buttonsState(), Controller::FeatureState::Available);
        QCOMPARE(controller.buttons()->count(), 6);
        QCOMPARE(controller.hapticEventsState(), Controller::FeatureState::Available);
        QCOMPARE(controller.hapticEvents()->count(), 3);
        QCOMPARE(controller.kdeActionsState(), Controller::FeatureState::Available);
        QCOMPARE(controller.waveforms().size(), 16);
        QVERIFY(controller.hasDefaults());
        QVERIFY(!controller.atDefaults());
        QVERIFY(!controller.needsSave());
        // localized labels come from the service; unknown actions get a readable fallback
        QCOMPARE(controller.actionLabel(action(u"kwin"_s, u"Overview"_s)), u"Basculer vers l'aperçu"_s);
        QVERIFY(controller.actionLabel(action(u"kwin"_s, u"Nope"_s)).contains(u"Nope"_s));
        QVERIFY(controller.actionLabel(QVariant::fromValue(nullptr)).isEmpty());

        // another device: its own settings, no haptics
        controller.setCurrentDeviceId(K850);
        QTRY_VERIFY_WITH_TIMEOUT(controller.isReady() && !controller.isLoading(), Timeout);
        QCOMPARE(controller.settings()->count(), 6);
        QCOMPARE(controller.hapticEventsState(), Controller::FeatureState::Unavailable);
        QCOMPARE(controller.buttons()->count(), 19);
    }

    void stagesAndAppliesSetting()
    {
        Controller controller;
        controller.load(); // as the KCM host does
        QTRY_VERIFY_WITH_TIMEOUT(controller.isReady(), Timeout);
        StagedModel *settings = controller.settings();
        const int dpi = settings->indexOf(u"dpi"_s);

        settings->stage(dpi, 2000.0);
        QVERIFY(controller.needsSave());
        settings->stage(dpi, 1600.0);
        QVERIFY(!controller.needsSave());
        settings->stage(dpi, 2000.0);
        QCOMPARE(deviceSetting(MX4, u"dpi"_s).toInt(), 1600); // nothing written before Apply

        QVERIFY(save(controller));
        QCOMPARE(settings->liveValue(dpi).toInt(), 2000);
        QVERIFY(!controller.needsSave());
        QCOMPARE(deviceSetting(MX4, u"dpi"_s).toInt(), 2000);

        // Reset drops edits and reloads
        settings->stage(settings->indexOf(u"smart-shift"_s), 30.0);
        QVERIFY(controller.needsSave());
        controller.load();
        QVERIFY(!controller.needsSave());
        QTRY_VERIFY_WITH_TIMEOUT(controller.isReady(), Timeout);
        QCOMPARE(settings->pendingValue(settings->indexOf(u"smart-shift"_s)).toInt(), 12);
    }

    void appliesPerKeyEdits()
    {
        Controller controller;
        controller.load(); // as the KCM host does
        QTRY_VERIFY_WITH_TIMEOUT(controller.isReady(), Timeout);
        StagedModel *settings = controller.settings();
        const int divert = settings->indexOf(u"divert-keys"_s);
        settings->stageKey(divert, u"82"_s, 1);
        QVERIFY(save(controller));
        QCOMPARE(deviceSetting(MX4, u"divert-keys"_s).toMap().value(u"82"_s).toInt(), 1);
        QCOMPARE(settings->liveValue(divert).toMap().value(u"195"_s).toInt(), 2); // the other keys untouched
        // the service re-announces the buttons, whose mode follows the diversion
        const int middle = controller.buttons()->indexOf(u"82"_s);
        QTRY_COMPARE_WITH_TIMEOUT(controller.buttons()->liveValue(middle).toMap().value(u"mode"_s).toString(), u"press"_s, Timeout);
    }

    void followsTheDevice()
    {
        Controller controller;
        controller.load(); // as the KCM host does
        QTRY_VERIFY_WITH_TIMEOUT(controller.isReady(), Timeout);
        StagedModel *settings = controller.settings();
        const int divert = settings->indexOf(u"divert-keys"_s);
        settings->stageKey(divert, u"83"_s, 1);

        // changed on the device meanwhile: another key, and a value that equals an edit
        QVariantMap onDevice = settings->liveValue(divert).toMap();
        onDevice.insert(u"86"_s, 2);
        mock(u"SetDeviceValue"_s, {MX4, u"divert-keys"_s, Json::serialize(onDevice)});
        QTRY_COMPARE_WITH_TIMEOUT(settings->liveValue(divert).toMap().value(u"86"_s).toInt(), 2, Timeout);
        QCOMPARE(settings->pendingValue(divert).toMap().value(u"83"_s).toInt(), 1);
        QCOMPARE(settings->pendingValue(divert).toMap().value(u"86"_s).toInt(), 2);

        const int smartShift = settings->indexOf(u"smart-shift"_s);
        settings->stage(smartShift, 20.0);
        mock(u"SetDeviceValue"_s, {MX4, u"smart-shift"_s, u"20"_s});
        QTRY_COMPARE_WITH_TIMEOUT(settings->liveValue(smartShift).toInt(), 20, Timeout);
        QVERIFY(!settings->data(settings->index(smartShift), StagedModel::ChangedRole).toBool());

        mock(u"SetOnline"_s, {MX4, false});
        QTRY_VERIFY_WITH_TIMEOUT(!controller.currentDevice().value(u"online"_s).toBool(), Timeout);
        mock(u"SetBattery"_s, {MX4, 12});
        QTRY_COMPARE_WITH_TIMEOUT(controller.currentDevice().value(u"battery"_s).toMap().value(u"level"_s).toInt(), 12, Timeout);
        QVERIFY(controller.needsSave()); // the edit of key 83 is still there
    }

    void stagesDefaults()
    {
        Controller controller;
        controller.load(); // as the KCM host does
        QTRY_VERIFY_WITH_TIMEOUT(controller.isReady(), Timeout);
        StagedModel *settings = controller.settings();
        controller.defaults();
        QVERIFY(controller.atDefaults());
        QVERIFY(controller.needsSave());
        QCOMPARE(settings->pendingValue(settings->indexOf(u"dpi"_s)).toInt(), 1000);
        QVERIFY(save(controller));
        QVERIFY(controller.atDefaults());
        QVERIFY(!controller.needsSave());
        QCOMPARE(deviceSetting(MX4, u"dpi"_s).toInt(), 1000);
        QCOMPARE(deviceSetting(MX4, u"divert-keys"_s).toMap().value(u"195"_s).toInt(), 0);
    }

    void reportsWriteErrors()
    {
        Controller controller;
        controller.load(); // as the KCM host does
        QTRY_VERIFY_WITH_TIMEOUT(controller.isReady(), Timeout);
        StagedModel *settings = controller.settings();
        const int smartShift = settings->indexOf(u"smart-shift"_s);
        settings->stage(smartShift, 30.0);
        settings->stage(settings->indexOf(u"dpi"_s), 2400.0);
        const int haptic = controller.buttons()->indexOf(u"416"_s);
        controller.buttons()->stageKey(haptic, u"mode"_s, u"off"_s);

        QVERIFY(save(controller, false));
        QVERIFY(controller.needsSave()); // the failed edits stay staged
        QVERIFY(!settings->writeError(smartShift).isEmpty());
        QVERIFY(!controller.buttons()->writeError(haptic).isEmpty());
        QVERIFY(controller.saveError().contains(settings->get(smartShift).value(u"label"_s).toString()));
        QCOMPARE(deviceSetting(MX4, u"dpi"_s).toInt(), 2400); // the others were applied
        QCOMPARE(deviceSetting(MX4, u"smart-shift"_s).toInt(), 12);

        // writing to an offline device fails cleanly too
        controller.setCurrentDeviceId(u"B03700000000-3F51C045"_s);
        QTRY_VERIFY_WITH_TIMEOUT(controller.isReady() && !controller.isLoading(), Timeout);
        QVERIFY(!controller.needsSave()); // edits do not follow to another device
        controller.settings()->stage(controller.settings()->indexOf(u"dpi"_s), 1200.0);
        QVERIFY(save(controller, false));
        QVERIFY(!controller.saveError().isEmpty());
        QVERIFY(!controller.settings()->writeError(controller.settings()->indexOf(u"dpi"_s)).isEmpty());
    }

    void appliesButtonActions()
    {
        Controller controller;
        controller.load(); // as the KCM host does
        QTRY_VERIFY_WITH_TIMEOUT(controller.isReady(), Timeout);
        StagedModel *buttons = controller.buttons();
        const int haptic = buttons->indexOf(u"416"_s);
        QCOMPARE(buttons->liveValue(haptic).toMap().value(u"press"_s).toMap(), action(u"kwin"_s, u"Overview"_s));

        buttons->stageKey(haptic, u"mode"_s, u"gesture"_s);
        buttons->stagePath(haptic, {u"gestures"_s, u"up"_s}, action(u"kwin"_s, u"Grid View"_s));
        buttons->stagePath(haptic, {u"gestures"_s, u"click"_s}, action(u"mediacontrol"_s, u"playpausemedia"_s));
        QVERIFY(save(controller));
        QVERIFY(!controller.needsSave());

        const QVariantMap onService = deviceButton(MX4, 416);
        QCOMPARE(onService.value(u"mode"_s).toString(), u"gesture"_s);
        QCOMPARE(onService.value(u"gestures"_s).toMap().value(u"up"_s).toMap(), action(u"kwin"_s, u"Grid View"_s));
        QCOMPARE(onService.value(u"gestures"_s).toMap().value(u"click"_s).toMap(), action(u"mediacontrol"_s, u"playpausemedia"_s));
        // the service diverts the button for gestures, and says so
        const int divert = controller.settings()->indexOf(u"divert-keys"_s);
        QTRY_COMPARE_WITH_TIMEOUT(controller.settings()->liveValue(divert).toMap().value(u"416"_s).toInt(), 2, Timeout);

        // clearing an action
        buttons->stagePath(haptic, {u"gestures"_s, u"click"_s}, QVariant::fromValue(nullptr));
        QVERIFY(save(controller));
        QVERIFY(deviceButton(MX4, 416).value(u"gestures"_s).toMap().value(u"click"_s).isNull());
    }

    void appliesHapticEvents()
    {
        Controller controller;
        controller.load(); // as the KCM host does
        QTRY_VERIFY_WITH_TIMEOUT(controller.isReady(), Timeout);
        StagedModel *events = controller.hapticEvents();
        events->stage(events->indexOf(u"battery_low"_s), u"WAVE"_s);
        events->stage(events->indexOf(u"notification"_s), QVariant::fromValue(nullptr));
        QVERIFY(save(controller));
        const QVariantList onService = api(u"GetHapticEvents"_s, {MX4}).toMap().value(u"events"_s).toList();
        for (const QVariant &event : onService) {
            const QVariantMap map = event.toMap();
            if (map.value(u"event"_s) == u"battery_low"_s) {
                QCOMPARE(map.value(u"waveform"_s).toString(), u"WAVE"_s);
            } else if (map.value(u"event"_s) == u"notification"_s) {
                QVERIFY(map.value(u"waveform"_s).isNull());
            }
        }
        QVERIFY(!controller.needsSave());

        // playing a waveform is immediate and has no visible effect besides errors
        controller.playHaptic(u"NOT A WAVEFORM"_s);
        QTRY_VERIFY_WITH_TIMEOUT(!controller.notice().isEmpty(), Timeout);
        controller.clearNotice();
        controller.playHaptic(u"WAVE"_s);
        QTest::qWait(300);
        QVERIFY(controller.notice().isEmpty());
    }

    void tracksServiceAvailability()
    {
        Controller controller;
        controller.load(); // as the KCM host does
        QTRY_VERIFY_WITH_TIMEOUT(controller.isReady(), Timeout);
        controller.settings()->stage(controller.settings()->indexOf(u"dpi"_s), 2000.0);

        mock(u"Quit"_s, {});
        QTRY_COMPARE_WITH_TIMEOUT(controller.serviceState(), Controller::ServiceState::Missing, Timeout);
        QVERIFY(controller.devices().isEmpty());
        QCOMPARE(controller.settings()->count(), 0);
        QVERIFY(!controller.needsSave());
        m_mock->waitForFinished(5000);
        delete m_mock;
        m_mock = nullptr;

        // no systemd on the private bus: starting the service reports why it failed
        controller.startService();
        QTRY_VERIFY_WITH_TIMEOUT(!controller.notice().isEmpty(), Timeout);

        startMock();
        QTRY_COMPARE_WITH_TIMEOUT(controller.serviceState(), Controller::ServiceState::Running, Timeout);
        QTRY_VERIFY_WITH_TIMEOUT(controller.isReady(), Timeout);
        QCOMPARE(controller.devices().size(), 3);
        QCOMPARE(controller.settings()->count(), 15);
    }

    void degradesWithAnOlderService()
    {
        Controller controller;
        controller.load(); // as the KCM host does
        QTRY_VERIFY_WITH_TIMEOUT(controller.isReady(), Timeout);
        QCOMPARE(controller.settings()->count(), 15);
        QCOMPARE(controller.buttonsState(), Controller::FeatureState::NeedsNewerService);
        QCOMPARE(controller.hapticEventsState(), Controller::FeatureState::NeedsNewerService);
        QCOMPARE(controller.kdeActionsState(), Controller::FeatureState::NeedsNewerService);
        QVERIFY(!controller.hasDefaults()); // no "default" in the settings: the Defaults button stays off
        QCOMPARE(controller.waveforms().size(), 16); // from the haptic-play setting
        controller.settings()->stage(controller.settings()->indexOf(u"dpi"_s), 2000.0);
        QVERIFY(save(controller));
    }
};

QTEST_GUILESS_MAIN(ControllerTest)

#include "controllertest.moc"
