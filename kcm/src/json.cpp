// SPDX-FileCopyrightText: 2026 plasmaar contributors
// SPDX-License-Identifier: GPL-2.0-or-later

#include "json.h"

#include <QJSValue>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonValue>

#include <cmath>
#include <limits>

namespace
{
QJsonValue toJsonValue(const QVariant &input)
{
    // values handed over from QML may still be wrapped JavaScript values
    const QVariant value = input.metaType() == QMetaType::fromType<QJSValue>() ? input.value<QJSValue>().toVariant() : input;
    switch (value.typeId()) {
    case QMetaType::UnknownType:
    case QMetaType::Nullptr:
        return QJsonValue(QJsonValue::Null);
    case QMetaType::Bool:
        return value.toBool();
    case QMetaType::Double:
    case QMetaType::Float: {
        const double d = value.toDouble();
        if (std::isfinite(d) && std::trunc(d) == d && std::abs(d) < double(std::numeric_limits<qint64>::max())) {
            return qint64(d);
        }
        return d;
    }
    case QMetaType::QVariantMap: {
        QJsonObject object;
        const QVariantMap map = value.toMap();
        for (auto it = map.cbegin(); it != map.cend(); ++it) {
            object.insert(it.key(), toJsonValue(it.value()));
        }
        return object;
    }
    case QMetaType::QVariantList:
    case QMetaType::QStringList: {
        QJsonArray array;
        const QVariantList list = value.toList();
        for (const QVariant &item : list) {
            array.append(toJsonValue(item));
        }
        return array;
    }
    default:
        break;
    }
    if (value.canConvert<QVariantMap>() && !value.canConvert<QString>()) {
        return toJsonValue(QVariant(value.toMap()));
    }
    if (value.canConvert<QVariantList>() && !value.canConvert<QString>()) {
        return toJsonValue(QVariant(value.toList()));
    }
    return QJsonValue::fromVariant(value);
}
}

namespace Json
{
QVariant parse(const QString &text, bool *ok)
{
    // QJsonDocument only takes objects and arrays at the top level; wrap scalars.
    QJsonParseError error;
    const QJsonDocument document = QJsonDocument::fromJson(QByteArray("[") + text.toUtf8() + QByteArray("]"), &error);
    const bool valid = error.error == QJsonParseError::NoError && document.isArray() && document.array().size() == 1;
    if (ok) {
        *ok = valid;
    }
    if (!valid) {
        return {};
    }
    const QJsonValue value = document.array().at(0);
    return value.isNull() ? QVariant::fromValue(nullptr) : value.toVariant();
}

QString serialize(const QVariant &value)
{
    const QByteArray wrapped = QJsonDocument(QJsonArray{toJsonValue(value)}).toJson(QJsonDocument::Compact);
    return QString::fromUtf8(wrapped.mid(1, wrapped.size() - 2));
}

QByteArray canonical(const QVariant &value)
{
    // QJsonObject keeps keys sorted, so the compact form is canonical.
    return QJsonDocument(QJsonArray{toJsonValue(value)}).toJson(QJsonDocument::Compact);
}
}
