#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 plasmaar contributors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run qmllint on the module's QML and fail on any warning, except unqualified access to the names that
KCMUtils and KI18n put into the QML context (the `kcm` object, i18n() and friends): qmllint cannot know
about context properties, and these are the documented way to reach them in a KCM.

    kcm/autotests/qmllint.py QMLLINT BUILD_BIN_DIR FILE.qml...
"""

import json
import re
import subprocess
import sys

CONTEXT_NAMES = {"kcm", "i18n", "i18nc", "i18np", "i18ncp", "xi18n", "xi18nc", "xi18np", "xi18ncp"}


def main(qmllint, import_dir, files):
    result = subprocess.run([qmllint, "--json", "-", "-I", import_dir, *files], capture_output=True, text=True)
    try:
        report = json.loads(result.stdout)
    except ValueError:
        print(result.stdout, result.stderr, sep="\n")
        return 1
    problems = 0
    for entry in report.get("files", []):
        filename = entry["filename"]
        lines = open(filename, encoding="utf-8").read().splitlines()
        for warning in entry.get("warnings", []):
            if warning.get("type") == "info":
                continue
            line, column = warning.get("line", 0), warning.get("column", 0)
            source = lines[line - 1] if 0 < line <= len(lines) else ""
            name = re.match(r"[A-Za-z_][A-Za-z0-9_]*", source[column - 1 :] if column else "")
            if warning.get("id") in ("unqualified", "context-properties") and name and name.group(0) in CONTEXT_NAMES:
                continue
            problems += 1
            print(f"{filename}:{line}:{column}: {warning.get('type')}: {warning.get('message')} [{warning.get('id')}]")
            if source:
                print("    " + source.strip())
        if not entry.get("success", True) and not entry.get("warnings"):
            problems += 1
            print(f"{filename}: qmllint failed")
    print(f"qmllint: {len(report.get('files', []))} files, {problems} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3:]))
