# SPDX-FileCopyrightText: 2026 plasmaar contributors
# SPDX-License-Identifier: GPL-2.0-or-later

cmake_minimum_required(VERSION 3.22)
project(kcm_plasmaar VERSION 0.1.0 LANGUAGES CXX)

set(QT_MIN_VERSION "6.6.0")
set(KF_MIN_VERSION "6.3.0") # Kirigami.SearchDialog

find_package(ECM ${KF_MIN_VERSION} REQUIRED NO_MODULE)
set(CMAKE_MODULE_PATH ${ECM_MODULE_PATH})

include(KDEInstallDirs)
include(KDECMakeSettings)
include(KDECompilerSettings NO_POLICY_SCOPE)
include(ECMQmlModule)
include(FeatureSummary)

find_package(Qt6 ${QT_MIN_VERSION} REQUIRED COMPONENTS Core DBus Gui Qml Quick)
find_package(KF6 ${KF_MIN_VERSION} REQUIRED COMPONENTS CoreAddons I18n KCMUtils)

option(BUILD_TESTING "Build the tests" ON)

add_compile_definitions(TRANSLATION_DOMAIN="kcm_plasmaar")
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# The D-Bus client, the staging model and the controller: a static QML module, so that the QML is typed
# (qmllint checks it against the generated .qmltypes) and the tests can use it without KCMUtils.
qt_add_library(plasmaar_kcm_core STATIC)
set_target_properties(plasmaar_kcm_core PROPERTIES POSITION_INDEPENDENT_CODE ON)
qt_add_qml_module(plasmaar_kcm_core
    URI io.github.fredaime.plasmaar
    VERSION 1.0
    NO_PLUGIN
    SOURCES
        src/controller.cpp src/controller.h
        src/json.cpp src/json.h
        src/plasmaarclient.cpp src/plasmaarclient.h
        src/stagedmodel.cpp src/stagedmodel.h
)
target_include_directories(plasmaar_kcm_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/src)
# The module's resource objects share the include directories, and may compile before AUTOMOC has created
# its include directory: create it up front for -Wmissing-include-dirs (set by KDECompilerSettings).
file(MAKE_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}/plasmaar_kcm_core_autogen/include)
target_link_libraries(plasmaar_kcm_core PUBLIC Qt6::Core Qt6::DBus Qt6::Gui Qt6::Qml KF6::I18n)

kcmutils_add_qml_kcm(kcm_plasmaar SOURCES src/plasmaarkcm.cpp src/plasmaarkcm.h)
target_link_libraries(kcm_plasmaar PRIVATE plasmaar_kcm_core KF6::CoreAddons KF6::I18n KF6::KCMUtilsQuick Qt6::Quick)

ki18n_install(po)

# For installs outside the system prefix (make install_kcm): the Plasma session environment script that
# adds the plugin directory to QT_PLUGIN_PATH.
configure_file(plasmaar-kcm.sh.in ${CMAKE_CURRENT_BINARY_DIR}/plasmaar-kcm.sh @ONLY)

if(BUILD_TESTING)
    add_subdirectory(autotests)
endif()

feature_summary(WHAT ALL INCLUDE_QUIET_PACKAGES FATAL_ON_MISSING_REQUIRED_PACKAGES)
