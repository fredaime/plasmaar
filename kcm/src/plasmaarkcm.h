// SPDX-FileCopyrightText: 2026 plasmaar contributors
// SPDX-License-Identifier: GPL-2.0-or-later

#pragma once

#include <KQuickConfigModule>

#include "controller.h"

/*
 * "Logitech Devices" in System Settings → Input Devices. The page itself is QML (ui/); this class hands
 * it the Controller and maps the KCM buttons (Apply, Reset, Defaults) onto it.
 */
class PlasmaarKcm : public KQuickConfigModule
{
    Q_OBJECT
    Q_PROPERTY(Controller *controller READ controller CONSTANT)

public:
    PlasmaarKcm(QObject *parent, const KPluginMetaData &metaData);

    Controller *controller() const;

    void load() override;
    void save() override;
    void defaults() override;

private:
    void updateState();

    Controller *m_controller;
};
