// SPDX-FileCopyrightText: 2026 plasmaar contributors
// SPDX-License-Identifier: GPL-2.0-or-later

#pragma once

#include <QByteArray>
#include <QString>
#include <QVariant>

// plasmaard payloads are JSON strings; these helpers convert them to and from QVariant.
namespace Json
{
// Parses any JSON value (also scalars such as "1200" or "true"). Sets ok to false on malformed input.
QVariant parse(const QString &text, bool *ok = nullptr);

// Serializes a QVariant (maps, lists, numbers, booleans, strings, null) as compact JSON.
// Integral doubles (QML numbers) are written as integers, because plasmaard checks for ints.
QString serialize(const QVariant &value);

// A canonical form for comparing values regardless of their C++ number types or map order.
QByteArray canonical(const QVariant &value);

inline bool equal(const QVariant &a, const QVariant &b)
{
    return canonical(a) == canonical(b);
}
}
