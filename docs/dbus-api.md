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

## Signals

| Signal | Args |
|---|---|
| `DeviceAdded` | `s` device JSON |
| `DeviceChanged` | `s` device JSON (online state, battery, …) |
| `DeviceRemoved` | `s` device_id |
| `SettingChanged` | `s` device_id, `s` name, `s` value JSON — after API writes and changes made on the device itself |

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
`value` (or `null` plus `error` if it could not be read).

| kind | extra fields | `SetSetting` value | `SetSettingKey` |
|---|---|---|---|
| `TOGGLE` | | `true` / `false` | |
| `CHOICE` | `choices: [{value, name}]` | a choice value (int) or its name | |
| `RANGE` | `min`, `max` | int in [min, max] | |
| `MAP_CHOICE` | `keys: [{value, name, choices \| min,max}]` | | key (int), value from that key's choices/range |

Other kinds (`MULTIPLE_TOGGLE`, `MULTIPLE_RANGE`, `PACKED_RANGE`, `HETERO`, …) are listed with
`writable: false` for now.

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
```
