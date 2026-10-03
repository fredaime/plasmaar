# Desktop events: haptic feedback and per-app rules

Two ways `plasmaard` follows what happens on the Plasma desktop:

- **Haptic events**: a mouse with haptics (MX Master 4) plays a waveform when a notification
  arrives, when the virtual desktop changes, or when a battery runs low.
- **Per-app rules**: a small KWin script tells `plasmaard` which window has the focus, so the
  `Process` condition in `rules.yaml` works on Plasma Wayland.

## Haptic events

### Events

| Event | Plays when | Not when |
|---|---|---|
| `notification` | An application asks the notification server (`org.freedesktop.Notifications`) to show a new notification | Do Not Disturb is on (the server's `Inhibited` property); plasmaar's own notifications; updates of a notification already shown (`replaces_id` ≠ 0); low-urgency notifications, which Plasma keeps out of popups by default |
| `desktop_switch` | KWin switches the virtual desktop (`org.kde.KWin.VirtualDesktopManager.currentChanged`), whether by keyboard, pager, or a mouse gesture | |
| `battery_low` | The battery of **any** plasmaar device drops to 10 % or below while discharging, once. It fires again only after that battery went back above 15 %. Also fires once at startup if a battery is already that low | Charging; a device that went offline (its last level is stale) |

`battery_low` is not tied to the device that plays it: the K850 cannot buzz, but when its
battery runs low the MX Master 4 can tell you. Plasma still shows its own low-battery warnings.

Each device has its own mapping from event to waveform. A device plays only while it is online,
only the waveforms it supports (`haptic-play`), and only events that have a waveform.

### Rate limiting

A device plays at most once every 300 ms, so a burst of notifications gives one buzz, not a
continuous one. If the device has not yet acknowledged the previous play (asleep, out of
range), new plays for it are dropped instead of piling up.

### Configure over D-Bus

The KDE settings page uses these methods; `busctl` works too. Both return the same JSON.

```sh
B="busctl --user call io.github.fredaime.Plasmaar /io/github/fredaime/Plasmaar io.github.fredaime.Plasmaar1"
ID=B04200000000-BD2BC136                                      # from ListDevices
$B GetHapticEvents s $ID
$B SetHapticEvent sss $ID notification "HAPPY ALERT"
$B SetHapticEvent sss $ID desktop_switch "SHARP STATE CHANGE"
$B SetHapticEvent sss $ID battery_low "ANGRY ALERT"
$B SetHapticEvent sss $ID notification ""                     # off
```

| Method | In | Out |
|---|---|---|
| `GetHapticEvents` | `s` device_id | `s` JSON (below) |
| `SetHapticEvent` | `s` device_id, `s` event, `s` waveform (`""` turns the event off) | `s` JSON (below) |

```json
{"device_id": "B04200000000-BD2BC136",
 "waveforms": ["SHARP STATE CHANGE", "DAMP STATE CHANGE", "HAPPY ALERT", "WAVE", "..."],
 "events": [{"event": "notification", "label": "New notification", "waveform": "HAPPY ALERT"},
            {"event": "desktop_switch", "label": "Virtual desktop switched", "waveform": null},
            {"event": "battery_low", "label": "Battery low", "waveform": null}]}
```

`waveforms` lists what the device supports; names are exact (as in `PlayHaptic`). Try one with
`$B PlayHaptic ss $ID WAVE` before mapping it. Errors (`io.github.fredaime.Plasmaar1.Error.*`):
`NoSuchDevice`; `NotSupported` (the device cannot play waveforms, e.g. the K850);
`InvalidValue` (unknown event or waveform); `DeviceOffline` (the device was never seen online
since `plasmaard` started, so its waveforms are unknown).

The mapping is saved with the device's other settings in `~/.config/plasmaar/config.yaml`:

```yaml
- _NAME: MX Master 4
  _haptic_events: {battery_low: ANGRY ALERT, desktop_switch: SHARP STATE CHANGE, notification: HAPPY ALERT}
  ...
```

The overall feedback strength is the device's `haptic-level` setting (0 turns haptics off).

### Without the D-Bus API, and turning it off

The event sources only *listen* on the session bus; they do not need plasmaar's own D-Bus
service. With `plasmaard --no-dbus` the events still play, using the mapping saved in
`config.yaml` (it just cannot be changed over D-Bus). `plasmaard --no-haptic-events` turns the
whole feature off: no notification monitor, no KWin subscription, no battery check.

### How notifications are seen, and privacy

Notifications are method calls to the notification server, not broadcasts. `plasmaard` opens a
separate private connection to the session bus and turns it into a bus **monitor** that only
receives `Notify` calls (`org.freedesktop.DBus.Monitoring.BecomeMonitor`, allowed for your own
session bus). It looks at the application name, `replaces_id` and the `desktop-entry`/`urgency`
hints only. Summaries and bodies are never read, logged or stored. If the bus refuses the
monitor, `journalctl --user -u plasmaard` says so and the other events keep working.

## Per-app rules on Plasma Wayland

On Wayland, applications cannot ask which window has the focus, so Solaar's `Process`
condition used to work only on X11 (or on GNOME with Solaar's GNOME extension). The
`plasmaar-focus` KWin script reports the active window to `plasmaard` on every focus change
(`SetActiveWindow`), and `Process` uses that report.

### Install the KWin script

```sh
make install_kwin_script      # installs (or upgrades), enables and loads it
make uninstall_kwin_script
```

This installs the package under `~/.local/share/kwin/scripts/plasmaar-focus` with
`kpackagetool6`, enables it in `kwinrc` (`[Plugins] plasmaar-focusEnabled=true`; it also shows in
System Settings → Window Management → KWin Scripts) and loads it into the running KWin (a running
KWin only loads newly enabled scripts at the next login otherwise). Check it runs:

```sh
qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.isScriptLoaded plasmaar-focus   # true
```

The script reports the window at load and on every activation, so after `plasmaard` restarts,
`Process` matches from the next window switch on. If a `Process` condition is evaluated before
any report arrived, the journal says that the KWin script seems to be missing.

### Matching

`Process: <text>` is true when the focused window's **resource class**, **resource name**, or
**process name** starts with `<text>` (on X11 the same with the window's instance, class and
process name). For Firefox that is e.g. `org.mozilla.firefox` or `firefox`, and the process
`firefox` or `firefox-bin`, so `Process: firefox` matches all its packagings. To see what KWin
reports for a window, run `qdbus6 org.kde.KWin /KWin queryWindowInfo` and click the window
(look at `resourceClass` and `resourceName`).

### Example: a different gesture action in Firefox

Rules run in order and the first rule that ends with an action wins, so put the per-app rule
first. With the gesture button diverted for mouse gestures (see [kde-actions.md](kde-actions.md)):

```yaml
%YAML 1.3
---
- Process: firefox
- MouseGesture: Mouse Up
- KdeShortcut: [kwin, Window Fullscreen]
...
---
- MouseGesture: Mouse Up
- KdeShortcut: [kwin, Grid View]
...
```

Gesture up toggles full screen in Firefox and shows the desktop grid everywhere else.

`MouseProcess` (the window under the pointer) is not reported by the script and still only
works on X11 and GNOME.
