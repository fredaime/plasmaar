UDEV_RULE_FILE = 42-plasmaar.rules
UDEV_RULE_FILE_UINPUT = 42-plasmaar-uinput.rules
UDEV_RULES_SOURCE := rules.d/$(UDEV_RULE_FILE)
UDEV_RULES_SOURCE_UINPUT := rules.d/$(UDEV_RULE_FILE_UINPUT)
UDEV_RULES_DEST := /etc/udev/rules.d/

PIP_ARGS ?= .

.PHONY: install_ubuntu install_macos
.PHONY: install_apt install_brew install_pip
.PHONY: install_udev install_udev_uinput reload_udev uninstall_udev install_user_service uninstall_user_service install_desktop_entry
.PHONY: format lint test

install_ubuntu: install_apt install_udev_uinput install_pip

install_macos: install_brew install_pip

install_apt:
	@echo "Installing Solaar dependencies via apt"
	sudo apt update
	sudo apt install libdbus-1-dev libglib2.0-dev libgtk-3-dev libgirepository1.0-dev

install_apt_python3.13:
	@echo "Installing Solaar dependencies via apt"
	sudo apt update
	sudo apt install libdbus-1-dev libglib2.0-dev libgtk-3-dev libgirepository-2.0-dev gobject-introspection

install_dnf:
	@echo "Installing Solaar dependencies via dnf"
	sudo dnf install gtk3 python3-devel python3-gobject python3-dbus python3-pyudev python3-psutil python3-xlib python3-yaml

install_brew:
	@echo "Installing Solaar dependencies via brew"
	brew update
	brew install hidapi gtk+3 pygobject3 gobject-introspection

install_pip:
	@echo "Installing Solaar via pip"
	python -m pip install --upgrade pip
	pip install $(PIP_ARGS)

install_pipx:
	@echo "Installing Solaar via pipx"
	pipx install --system-site-packages $(PIP_ARGS)

install_udev:
	@echo "Copying plasmaar udev rule (Logitech hidraw access) to $(UDEV_RULES_DEST)"
	sudo install -m 644 $(UDEV_RULES_SOURCE) $(UDEV_RULES_DEST)
	make reload_udev

install_udev_uinput: install_udev
	@echo "Copying plasmaar udev rule (uinput access) to $(UDEV_RULES_DEST)"
	sudo install -m 644 $(UDEV_RULES_SOURCE_UINPUT) $(UDEV_RULES_DEST)
	make reload_udev

reload_udev:
	@echo "Reloading udev rules and applying them to connected devices"
	sudo udevadm control --reload-rules
	sudo udevadm trigger --subsystem-match=hidraw --subsystem-match=misc --action=change

PLASMAARD ?= $(shell command -v plasmaard)
USER_UNIT_DIR := $(HOME)/.config/systemd/user

DESKTOP_ENTRY := io.github.fredaime.plasmaar.desktop
USER_APPLICATIONS_DIR := $(HOME)/.local/share/applications

install_desktop_entry:
	@echo "Installing $(DESKTOP_ENTRY) (notification identity)"
	install -D -m 644 share/applications/$(DESKTOP_ENTRY) $(USER_APPLICATIONS_DIR)/$(DESKTOP_ENTRY)
	-update-desktop-database $(USER_APPLICATIONS_DIR)

install_user_service: install_desktop_entry
	@test -n "$(PLASMAARD)" || { echo "plasmaard not found; install plasmaar or pass PLASMAARD=/path/to/plasmaard"; exit 1; }
	@echo "Installing plasmaard user service running $(PLASMAARD)"
	mkdir -p $(USER_UNIT_DIR)
	sed 's|^ExecStart=.*|ExecStart=$(PLASMAARD)|' share/systemd/user/plasmaard.service > $(USER_UNIT_DIR)/plasmaard.service
	systemctl --user daemon-reload
	systemctl --user enable --now plasmaard.service

uninstall_user_service:
	-systemctl --user disable --now plasmaard.service
	rm -f $(USER_UNIT_DIR)/plasmaard.service $(USER_APPLICATIONS_DIR)/$(DESKTOP_ENTRY)
	systemctl --user daemon-reload

# KWin script reporting the active window to plasmaard (Process rules on Plasma Wayland, docs/desktop-events.md)
KWIN_SCRIPT := plasmaar-focus
KWIN_SCRIPT_SOURCE := share/kwin/scripts/$(KWIN_SCRIPT)
KWIN_SCRIPT_INSTALLED := $(HOME)/.local/share/kwin/scripts/$(KWIN_SCRIPT)

.PHONY: install_kwin_script uninstall_kwin_script

# install or upgrade, enable, then unload a running copy so that reconfigure (re)loads the new code
install_kwin_script:
	@echo "Installing and enabling the $(KWIN_SCRIPT) KWin script"
	kpackagetool6 --type KWin/Script --upgrade $(KWIN_SCRIPT_SOURCE) 2>/dev/null || kpackagetool6 --type KWin/Script --install $(KWIN_SCRIPT_SOURCE)
	kwriteconfig6 --file kwinrc --group Plugins --key $(KWIN_SCRIPT)Enabled true
	-qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript $(KWIN_SCRIPT)
	@# A running KWin only loads enabled scripts at session start (reconfigure and Scripting.start() don't),
	@# so load and run the installed copy now; from the next login KWin loads it from kwinrc by itself.
	id=$$(qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.loadScript $(KWIN_SCRIPT_INSTALLED)/contents/code/main.js $(KWIN_SCRIPT)) \
		&& qdbus6 org.kde.KWin /Scripting/Script$$id org.kde.kwin.Script.run
	qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.isScriptLoaded $(KWIN_SCRIPT)

uninstall_kwin_script:
	kwriteconfig6 --file kwinrc --group Plugins --key $(KWIN_SCRIPT)Enabled --delete
	-qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript $(KWIN_SCRIPT)
	-qdbus6 org.kde.KWin /KWin reconfigure
	-kpackagetool6 --type KWin/Script --remove $(KWIN_SCRIPT)

uninstall_udev:
	@echo "Removing plasmaar udev rules from $(UDEV_RULES_DEST)"
	sudo rm -f $(UDEV_RULES_DEST)/$(UDEV_RULE_FILE) $(UDEV_RULES_DEST)/$(UDEV_RULE_FILE_UINPUT)
	make reload_udev

format:
	@echo "Formatting Solaar code"
	ruff format .

lint:
	@echo "Linting Solaar code"
	ruff check . --fix

test:
	@echo "Running Solaar tests"
	pytest -rs --cov --cov-report=xml
