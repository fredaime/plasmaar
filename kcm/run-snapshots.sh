#!/bin/bash
# SPDX-FileCopyrightText: 2026 plasmaar contributors
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Render the module headless and save PNG snapshots of every page (see docs/kcm.md):
#
#   kcm/run-snapshots.sh [options] PREFIX       ->  PREFIX-<device>-<page>.png
#
#   --build DIR       build directory of kcm/ (default: kcm/build)
#   --lang LANG       UI language (default: fr)
#   --legacy          mock: v1 API only, like a plasmaard without the additions
#   --fail NAME       mock: make writes of this setting fail (repeatable)
#   --scenario apply-errors
#                     mock: stage and apply a few edits first (use with --fail smart-shift)
#   --no-service      no service at all (the "plasmaard is not running" page)
#   --real            the plasmaard on your session bus instead of the mock (read-only: snapshot
#                     mode never writes, and --scenario is refused)
#
# The mock runs on a private D-Bus session without service activation, so nothing touches your devices or
# desktop services. The window is offscreen either way and never shows on screen.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
repo=$(dirname "$here")
build="$here/build"
lang=fr
real=0
service=1
scenario=""
mock_args=()
while [ $# -gt 1 ]; do
    case "$1" in
        --build) build=$(cd "$2" && pwd); shift ;;
        --lang) lang=$2; shift ;;
        --legacy) mock_args+=(--legacy) ;;
        --fail) mock_args+=(--fail "$2"); shift ;;
        --scenario) scenario=$2; shift ;;
        --no-service) service=0 ;;
        --real) real=1 ;;
        --inner) ;;
        *) echo "unknown option $1" >&2; exit 2 ;;
    esac
    shift
done
prefix=${1:?"usage: $0 [options] PREFIX (see the top of this script)"}
mkdir -p "$(dirname "$prefix")"
prefix=$(cd "$(dirname "$prefix")" && pwd)/$(basename "$prefix")

if [ ! -e "$build/bin/plasma/kcms/systemsettings/kcm_plasmaar.so" ]; then
    echo "build the module first: cmake -S kcm -B $build && cmake --build $build" >&2
    exit 1
fi

run_module() {
    export QT_QPA_PLATFORM=offscreen
    export QT_PLUGIN_PATH="$build/bin${QT_PLUGIN_PATH:+:$QT_PLUGIN_PATH}"
    export XDG_DATA_DIRS="$build:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}" # translations
    export QT_QUICK_CONTROLS_STYLE=${QT_QUICK_CONTROLS_STYLE:-org.kde.desktop}
    export QT_QPA_PLATFORMTHEME=${QT_QPA_PLATFORMTHEME:-kde}
    export LANGUAGE=$lang
    export PLASMAAR_KCM_SNAPSHOT=$prefix
    export PLASMAAR_KCM_SNAPSHOT_SCENARIO=$scenario
    timeout 180 kcmshell6 kcm_plasmaar
}

if [ "$real" = 1 ]; then
    if [ -n "$scenario" ]; then
        echo "--scenario writes settings: only against the mock" >&2
        exit 2
    fi
    run_module
elif [ -z "${PLASMAAR_SNAPSHOT_BUS:-}" ]; then
    # re-run inside a private session bus
    export QT_QPA_PLATFORM=offscreen
    args=(--inner --build "$build" --lang "$lang")
    [ -n "$scenario" ] && args+=(--scenario "$scenario")
    [ "$service" = 0 ] && args+=(--no-service)
    PLASMAAR_SNAPSHOT_BUS=1 exec dbus-run-session --config-file="$here/autotests/isolated-bus.conf" -- \
        "$0" "${args[@]}" "${mock_args[@]}" "$prefix"
else
    if [ "$service" = 1 ]; then
        LANGUAGE=$lang python3 "$repo/tools/mock_plasmaard.py" "${mock_args[@]}" &
        mock=$!
        trap 'kill $mock 2>/dev/null || true' EXIT
        for _ in $(seq 50); do
            busctl --user status io.github.fredaime.Plasmaar >/dev/null 2>&1 && break
            sleep 0.1
        done
    fi
    run_module
fi
