# plasmaar roadmap

plasmaar is an independent fork of [Solaar](https://github.com/pwr-Solaar/Solaar).
It keeps Solaar's Logitech HID++ protocol core and replaces the GTK application with a
headless service plus native KDE Plasma integration. Nothing is contributed back upstream.
The `upstream` remote is fetch-only, for optional cherry-picks of new device support.

Reference hardware: MX Master 4 (Bluetooth `046d:B042`) and K850 keyboard.

## Part 0: What stays cleanly outside the GUI

Measured on 2026-10-02 by importing each module with Gtk, Gdk, Notify and Xlib blocked.

| Layer | Status | Notes |
|---|---|---|
| `hidapi/`, `hid_parser/`, `keysyms/` | Clean | pyudev only; GLib only for hotplug monitoring (`monitor_glib`) |
| `logitech_receiver/` protocol core (`base`, `hidpp10/20`, `settings`, `settings_validator`, `descriptors`, `common`, `special_keys`, `listener`) | Clean | `base` and `listener` import with GUI libs blocked |
| `logitech_receiver/` `device`, `receiver`, `settings_templates`, `notifications` | **Fail to import** | Only because they import `diversion`, which needs Gdk. Their own code is GUI-free |
| `logitech_receiver/diversion.py` (rules engine) | Coupled | Gdk keymap + modifier masks (~12 uses), Xlib, evdev. On Wayland it already uses uinput |
| `logitech_receiver/desktop_notifications.py` | Partly coupled | libnotify, plus Gtk for an icon-theme lookup |
| `logitech_receiver/rgb_power.py` | Fine | GLib timers only |
| `solaar/` `configuration`, `dbus`, `tasks`, `upower`, `i18n` | Clean | |
| `solaar/listener.py` | Fine once `diversion` is fixed | GLib main loop; the UI is reached only through 3 callbacks (status changed, setting changed, error), which is the seam we use |
| `solaar/cli/` | Mostly clean | `config` forwards to a running instance via `Gtk.Application`; it will use D-Bus instead |
| `solaar/ui/`, `solaar/gtk.py` | To be replaced | GTK application |

Already native in Plasma, so we don't rebuild it: **battery**. The kernel's `hid-logitech-hidpp`
driver exposes `hidpp_battery_*`, UPower picks it up, and Plasma's battery widget and low-battery
warnings use it. The K850 is covered via BlueZ.

## Phase 0: Headless core and `plasmaard` (shared foundation)

**Status: done (2026-10-03).** 0.1 #4, 0.2 #5, 0.3 #7, 0.4 #8, 0.5 #9, 0.6 this change. Development setup:
`make install_udev` (device access for the seated user) and
`make install_user_service PLASMAARD=$PWD/.venv/bin/plasmaard` (starts with the Plasma session).

Both assessments below depend on this. Estimate: 3–4 sessions.

1. **Decouple `diversion`**: import it lazily from `settings_templates` and `notifications`,
   make Gdk optional, hard-code the modifier masks, look up keys via evdev/xkb on Wayland.
2. **Notifications without GTK**: use `org.freedesktop.Notifications` over D-Bus instead of libnotify.
3. **Own identity**: `~/.config/plasmaar/` and its own app ID, so plasmaar never fights an
   installed Solaar for the device.
4. **`plasmaard`**: a GLib main loop that wires the 3 listener callbacks to D-Bus signals.
   Reuses `solaar.dbus` for suspend/resume. Runs as a systemd user service.
5. **D-Bus API** on the session bus, `io.github.fredaime.Plasmaar` (`org.kde.*` belongs to the KDE project):
   - `ListDevices()`
   - `GetDevice(id)`: name, connection, firmware, battery
   - `ListSettings(id)`: normalized schema per setting (name, label, description, kind,
     choices, range, keys, value, display)
   - `SetSetting(id, name, value)`, `SetSettingKey(id, name, key, value)`
   - `PlayHaptic(id, waveform)`
   - Signals: `DeviceAdded`, `DeviceRemoved`, `DeviceChanged`, `SettingChanged`, `ButtonEvent`
6. **Device access without root**: udev rule for hidraw + uinput. Merge the pending fix branches
   (`fix/check-feature-settings-no-persister`, `fix/haptic-missing-replies`).

**Done when** `busctl --user call … ListSettings` returns the MX Master 4's settings with no
GTK installed, and the test suite stays green.

## Assessment A: Minimal Plasma integration outside the settings page

**Status:** A1 done (plasmaard user service, Phase 0.6). A2 done: notifications carry the
`io.github.fredaime.plasmaar` desktop entry. A4/A5 done as a `KdeShortcut` rule action plus
automatic reload of `rules.yaml` — see [kde-actions.md](kde-actions.md).

Goal: the mouse feels native in Plasma before any settings UI exists. No C++. Estimate: 4–6 sessions.

| # | Item | KDE mechanism | Effort |
|---|---|---|---|
| A1 | Session service: autostarts with Plasma, survives suspend and reconnects | systemd user unit, `graphical-session.target` | S |
| A2 | Notifications: connected/disconnected, "device needs attention" | freedesktop notifications + `plasmaar.notifyrc` + `.desktop` | S |
| A3 | Battery | Already native (UPower); only make sure we don't duplicate it | 0 |
| A4 | **Buttons → KDE actions**: divert gesture/haptic/thumb buttons and trigger KDE actions by name (e.g. gesture up → KWin Overview) | `org.kde.kglobalaccel` `invokeShortcut` over D-Bus; fallback: F13–F24 via uinput, bound in Plasma Shortcuts | M |
| A5 | Mappings in `plasmaar.yaml` until the settings page exists | YAML | S |
| A6 | Haptics on desktop events (notifications, virtual-desktop switch, low battery) | D-Bus signal watching → `PlayHaptic` | M |
| A7 | Per-app awareness on Wayland | KWin script reports the focused window to `plasmaard` | M, optional |

Minimal set: **A1 + A2 + A4 + A5**.

## Assessment B: The settings page (System Settings module)

Goal: "Logitech devices" under System Settings → Input Devices. Build deps (`libkf6kcmutils-dev`,
`qt6-declarative-dev`, `extra-cmake-modules`) are already installed on the dev machine.
Estimate: 6–9 sessions.

| # | Item | Effort |
|---|---|---|
| B1 | Skeleton: thin C++ plugin + QML page talking to `plasmaard` over D-Bus; appears in System Settings | M |
| B2 | Device header: picker, name, connection, firmware, battery | S |
| B3 | Settings drawn from the schema: TOGGLE → Switch, CHOICE → ComboBox (long lists such as DPI become a stepped slider), RANGE → Slider/SpinBox | M |
| B4 | Apply/Reset semantics: stage changes and write on Apply; "Defaults" = values captured when a device is first seen | S–M |
| B5 | Per-key maps: button remapping and diversion as a table | M |
| B6 | Button-actions editor: pick KDE actions from kglobalaccel; GUI over A4/A5, replaces Solaar's rules editor | M |
| B7 | Haptics panel: intensity + per-waveform "test" buttons | S |
| B8 | Advanced kinds: MULTIPLE_TOGGLE/RANGE, PACKED_RANGE, GRAPHIC_EQ, COLOR/RGB | L, deferred |
| B9 | Pairing UI for Bolt/Unifying receivers | Deferred |

Minimal set: **B1–B4 + B7**.

## Ordering

```
Phase 0 (headless core + plasmaard + D-Bus API)
   ├──► A: A1 → A2 → A4/A5      usable early, no C++
   └──► B: B1 → B2/B3 → B4 → B7 → B5/B6
```

A goes first: it gives daily value cheaply and road-tests the D-Bus API that B depends on.
B6 is a GUI over the A4/A5 configuration, so doing A4 first designs that data model once.

## Risks

- A diverted button only works while `plasmaard` is running; diversion must be undone on shutdown.
- If `invokeShortcut` can't reach an action, fall back to F13–F24 keys.
- Independent fork: new device support has to be cherry-picked from `upstream` deliberately.
