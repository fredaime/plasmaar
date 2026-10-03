UDEV_RULE_FILE = 42-plasmaar.rules
UDEV_RULE_FILE_UINPUT = 42-plasmaar-uinput.rules
UDEV_RULES_SOURCE := rules.d/$(UDEV_RULE_FILE)
UDEV_RULES_SOURCE_UINPUT := rules.d/$(UDEV_RULE_FILE_UINPUT)
UDEV_RULES_DEST := /etc/udev/rules.d/

PIP_ARGS ?= .

.PHONY: install_ubuntu install_macos
.PHONY: install_apt install_brew install_pip
.PHONY: install_udev install_udev_uinput reload_udev uninstall_udev install_user_service uninstall_user_service
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

install_user_service:
	@test -n "$(PLASMAARD)" || { echo "plasmaard not found; install plasmaar or pass PLASMAARD=/path/to/plasmaard"; exit 1; }
	@echo "Installing plasmaard user service running $(PLASMAARD)"
	mkdir -p $(USER_UNIT_DIR)
	sed 's|^ExecStart=.*|ExecStart=$(PLASMAARD)|' share/systemd/user/plasmaard.service > $(USER_UNIT_DIR)/plasmaard.service
	systemctl --user daemon-reload
	systemctl --user enable --now plasmaard.service

uninstall_user_service:
	-systemctl --user disable --now plasmaard.service
	rm -f $(USER_UNIT_DIR)/plasmaard.service
	systemctl --user daemon-reload

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
