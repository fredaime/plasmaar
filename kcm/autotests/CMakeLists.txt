# SPDX-FileCopyrightText: 2026 plasmaar contributors
# SPDX-License-Identifier: GPL-2.0-or-later

find_package(Qt6 ${QT_MIN_VERSION} REQUIRED COMPONENTS Test)
include(ECMAddTests)

ecm_add_test(stagedmodeltest.cpp TEST_NAME stagedmodeltest LINK_LIBRARIES plasmaar_kcm_core Qt6::Test)

# The controller against the mock service, on a private session bus without service activation.
find_program(DBUS_RUN_SESSION dbus-run-session)
find_program(PYTHON3 python3)
if(DBUS_RUN_SESSION AND PYTHON3)
    add_executable(controllertest controllertest.cpp)
    target_link_libraries(controllertest plasmaar_kcm_core Qt6::Test)
    add_test(NAME controllertest
             COMMAND ${DBUS_RUN_SESSION} --config-file=${CMAKE_CURRENT_SOURCE_DIR}/isolated-bus.conf -- $<TARGET_FILE:controllertest>)
    set_tests_properties(controllertest PROPERTIES
        ENVIRONMENT "PLASMAAR_MOCK=${CMAKE_CURRENT_SOURCE_DIR}/../../tools/mock_plasmaard.py;PLASMAAR_PYTHON=${PYTHON3}"
        TIMEOUT 300)
else()
    message(STATUS "dbus-run-session or python3 missing: controllertest is not built")
endif()

# QML: lint the module's pages against the generated types of the C++ module (also run in CI).
find_program(QMLLINT qmllint PATHS ${QT6_INSTALL_PREFIX}/${QT6_INSTALL_BINS} /usr/lib/qt6/bin /usr/lib64/qt6/bin)
if(QMLLINT AND PYTHON3)
    file(GLOB qml_files ${CMAKE_CURRENT_SOURCE_DIR}/../ui/*.qml)
    add_test(NAME qmllint COMMAND ${PYTHON3} ${CMAKE_CURRENT_SOURCE_DIR}/qmllint.py ${QMLLINT} ${CMAKE_BINARY_DIR}/bin ${qml_files})
endif()
