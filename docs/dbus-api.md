# plasmaar D-Bus API (v1)

`plasmaard` exposes its devices on the **session bus**:

| | |
|---|---|
| Bus name | `io.github.fredaime.Plasmaar` |
| Object path | `/io/github/fredaime/Plasmaar` |
| Interface | `io.github.fredaime.Plasmaar1` (the `1` is the API version) |

Payloads are **JSON strings**. Setting values range from booleans to per-key maps; JSON keeps
them uniform and is parsed natively by QML (`JSON.parse`). JSON object keys are strings, so
integer keys (button ids, …) appear as decimal strings, e.g. `{"416": 0}`.

Every call that needs the device runs on a worker thread in the daemon, so a slow or sleeping
device never blocks other clients.

## Methods

| Method | In | Out |
|---|---|---|
| `GetVersion` | | `s` API version (`"1"`) |
| `ListDevices` | | `s` JSON array of devices |
| `ListSettings` | `s` device_id | `s` JSON array of settings |
| `SetSetting` | `s` device_id, `s` name, `s` value_json | `s` stored value (JSON) |
| `SetSettingKey` | `s` device_id, `s` name, `s` key_json, `s` value_json | `s` stored value (JSON, whole map) |
| `PlayHaptic` | `s` device_id, `s` waveform name | |
| `ListKdeActions` | | `s` JSON array of KDE actions, by component ([below](#kde-actions-json)) |
| `GetButtonActions` | `s` device_id | `s` JSON object with the device's buttons ([below](#button-actions)) |
| `SetButtonAction` | `s` device_id, `i` control, `s` config_json | `s` the updated button (JSON) |

## Signals

| Signal | Args |
|---|---|
| `DeviceAdded` | `s` device JSON |
| `DeviceChanged` | `s` device JSON (online state, battery, …) |
| `DeviceRemoved` | `s` device_id |
| `SettingChanged` | `s` device_id, `s` name, `s` value JSON — after API writes and changes made on the device itself |
| `ButtonActionsChanged` | `s` device_id — after `SetButtonAction`, a `divert-keys` write that changes a managed button, or an edit of `buttons.yaml` |

These methods and signals were added to API v1 without breaking it, so `GetVersion` still
returns `"1"`. A client that needs them can check for them in the introspection data.

## Device JSON

```json
{"id": "B04200000000-BD2BC136", "name": "MX Master 4", "codename": "MX Master 4",
 "kind": "mouse", "online": true, "protocol": 4.5, "model_id": "B04200000000",
 "unit_id": "BD2BC136", "serial": "", "battery": {"level": 45, "status": "DISCHARGING"}}
```

`id` is `<model_id>-<unit_id>` when the device reports them (stable across reconnects),
otherwise `<path>#<number>`.

## Setting JSON

Common fields: `name`, `label`, `description`, `kind`, `display` (show in UIs), `writable`,
`value` (or `null` plus `error` if it could not be read), and `default` when it is known.

`default` is the value the setting had the first time plasmaar saw the device online, for a
"Defaults" button in a settings UI. It has the same shape as `value`. Two settings use their
factory state instead, whatever they held at that point: `divert-keys` defaults to every key
`0` (Regular), and `reprogrammable-keys` defaults to every key mapped to itself. Only writable
kinds get a default, and settings that are never saved (such as `haptic-play`) get none.
Defaults are captured when the device is first announced (`DeviceAdded`) or listed, and saved in
`config.yaml` under the device's `_defaults` entry. A captured value is never overwritten. A
setting with no captured value (because it was unreadable, or added by a newer plasmaar) gets
its current value at the next start of `plasmaard`.

| kind | extra fields | `SetSetting` value | `SetSettingKey` |
|---|---|---|---|
| `TOGGLE` | | `true` / `false` | |
| `CHOICE` | `choices: [{value, name}]` | a choice value (int) or its name | |
| `RANGE` | `min`, `max` | int in [min, max] | |
| `MAP_CHOICE` | `keys: [{value, name, choices \| min,max}]` | | key (int), value from that key's choices/range |

Other kinds (`MULTIPLE_TOGGLE`, `MULTIPLE_RANGE`, `PACKED_RANGE`, `HETERO`, …) are listed with
`writable: false` for now.

## KDE actions JSON

`ListKdeActions` lists the global-shortcut actions that a button can run, read from kglobalaccel
(all components, default context only). Components are sorted by label, and so are the actions
inside each one. Components with no actions are left out.

```json
[{"component": "kwin", "label": "KWin",
  "actions": [{"name": "Grid View", "label": "Basculer vers l'affichage en grille"},
              {"name": "Overview", "label": "Basculer vers l'aperçu"}, …]},
 {"component": "org.kde.spectacle.desktop", "label": "Spectacle", "actions": […]}, …]
```

`component` and `name` are the stable ids that `SetButtonAction` and the `KdeShortcut` rule action
take. `label` is the localized friendly name, for display only. The call fails with `Failed` when
kglobalaccel is not reachable. It never starts kglobalaccel.

## Button actions

A *button* is a key of the device's `divert-keys` setting. Each button is in one of three
modes, which map to that key's `divert-keys` values:

| mode | `divert-keys` | the button… |
|---|---|---|
| `off` | 0 Regular | does its normal job |
| `press` | 1 Diverted | runs its `press` action when pressed |
| `gesture` | 2 Mouse Gestures | runs a `gestures` action when released: `up`, `down`, `left`, `right` after a swipe (a pause halfway is fine), `click` without moving |

`GetButtonActions(device_id)`:

```json
{"device_id": "B04200000000-BD2BC136",
 "buttons": [
  {"control": 416, "name": "Haptic", "modes": ["off", "press"], "mode": "press",
   "press": {"component": "kwin", "action": "Overview"},
   "gestures": {"up": null, "down": null, "left": null, "right": null, "click": null}},
  {"control": 195, "name": "Mouse Gesture Button", "modes": ["off", "press", "gesture"], "mode": "gesture",
   "press": null,
   "gestures": {"up": {"component": "kwin", "action": "Grid View"}, "down": null, "left": null,
                "right": null, "click": null}}]}
```

`modes` lists the modes the key supports. Other `divert-keys` choices, such as Sliding DPI, are
not exposed. `mode` is the key's current `divert-keys` value, mapped as in the table above. Any
other value reads as `off`. `press` and `gestures` are the stored actions, `null` when unset.
Actions stay stored for modes that are not active, so switching modes back restores them. This
works offline, using the last known diversion.

`SetButtonAction(device_id, control, config_json)` returns the updated button, in the same shape:

```json
{"mode": "gesture",
 "press": {"component": "kwin", "action": "Overview"},
 "gestures": {"up": {"component": "kwin", "action": "Grid View"}, "click": null}}
```

- Every field is optional. A missing field keeps its current value, and `gestures` is merged per
  direction, with `null` removing that direction. `press: null` removes the press action.
- `mode` is written to `divert-keys[control]` through the setting, so it is saved and re-applied
  when the device reconnects. This needs the device online. Without `mode` the call only changes
  the actions, so it also works while the device is offline.
- The actions are saved to `~/.config/plasmaar/buttons.yaml` and the button rules are regenerated
  at once (see [kde-actions.md](kde-actions.md)).
- Signals: `SettingChanged` for `divert-keys` (only when `mode` was given), then
  `ButtonActionsChanged(device_id)`.
- Errors: `NoSuchDevice`; `DeviceOffline` (a `mode` while the device is offline); `InvalidValue`
  (unknown control, unknown mode, unknown direction or field, malformed action, or input that is
  not a JSON object); `NotSupported` (the device has no `divert-keys`, or the key does not support
  that mode). Nothing is written when the input is invalid.

A `divert-keys` change made with `SetSettingKey` updates the mode of a managed button too (the
button rules follow it, and `ButtonActionsChanged` is emitted). A front-end can therefore treat
`GetButtonActions` as the source of truth after either signal.

## Errors

D-Bus error names are `io.github.fredaime.Plasmaar1.Error.<Name>`:
`NoSuchDevice`, `NoSuchSetting`, `InvalidValue`, `NotSupported`, `DeviceOffline`, `Failed`.

## Examples

```sh
B="busctl --user call io.github.fredaime.Plasmaar /io/github/fredaime/Plasmaar io.github.fredaime.Plasmaar1"
$B ListDevices
$B ListSettings s B04200000000-BD2BC136
$B SetSetting sss B04200000000-BD2BC136 smart-shift 15
$B SetSettingKey ssss B04200000000-BD2BC136 divert-keys 416 1
$B PlayHaptic ss B04200000000-BD2BC136 WAVE
dbus-monitor --session "interface='io.github.fredaime.Plasmaar1'"

# button actions
$B ListKdeActions
$B GetButtonActions s B04200000000-BD2BC136
$B SetButtonAction sis B04200000000-BD2BC136 416 '{"mode": "press", "press": {"component": "kwin", "action": "Overview"}}'
$B SetButtonAction sis B04200000000-BD2BC136 195 '{"mode": "gesture", "gestures": {"up": {"component": "kwin", "action": "Grid View"}}}'
$B SetButtonAction sis B04200000000-BD2BC136 195 '{"gestures": {"up": null}}'   # remove one gesture
$B SetButtonAction sis B04200000000-BD2BC136 416 '{"mode": "off"}'               # normal button, action kept

# pretty-print a JSON reply
busctl --user --json=short call io.github.fredaime.Plasmaar /io/github/fredaime/Plasmaar \
  io.github.fredaime.Plasmaar1 ListKdeActions | jq -r '.data[0]' | jq .
```
