#!/bin/sh
# SPDX-FileCopyrightText: 2026 plasmaar contributors
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Extracts the module's messages into po/kcm_plasmaar.pot and merges them into the translations:
#   kcm/Messages.sh
# (Same keywords as KDE's scripty; QML is read as JavaScript.)
set -e
cd "$(dirname "$0")"
KEYWORDS="-ki18n:1 -ki18nc:1c,2 -ki18np:1,2 -ki18ncp:1c,2,3 -kxi18n:1 -kxi18nc:1c,2 -kxi18np:1,2 -kxi18ncp:1c,2,3 -kkli18n:1 -kkli18nc:1c,2"
COMMON="--from-code=UTF-8 --add-comments=i18n --package-name=kcm_plasmaar --msgid-bugs-address=https://github.com/fredaime/plasmaar/issues"
xgettext $COMMON -C $KEYWORDS -o po/cpp.pot src/*.cpp
xgettext $COMMON -L JavaScript $KEYWORDS -o po/qml.pot ui/*.qml
msgcat --use-first po/cpp.pot po/qml.pot -o po/kcm_plasmaar.pot
rm -f po/cpp.pot po/qml.pot
for po in po/*/kcm_plasmaar.po; do
    [ -e "$po" ] || continue
    msgmerge --quiet --update --backup=none --no-fuzzy-matching "$po" po/kcm_plasmaar.pot
done
