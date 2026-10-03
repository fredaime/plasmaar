# Mouse buttons → KDE actions

A **diverted** button stops doing its normal job and reports to `plasmaard` instead. `plasmaard`
then runs a KDE global-shortcut action **by name** through kglobalaccel. No key binding or input
injection is needed. There are two ways to set this up:

- **Managed button actions** (recommended): one call per button with `SetButtonAction`, which
  diverts the button and maps it in one step. The System Settings page will offer the same thing.
  They are stored in `~/.config/plasmaar/buttons.yaml`.
- **Custom rules** in `~/.config/plasmaar/rules.yaml`, for anything a single action per
  button or gesture cannot express: conditions, other actions, multi-step gestures.

Both files are reloaded automatically when they change.

## Managed button actions

```sh
B="busctl --user call io.github.fredaime.Plasmaar /io/github/fredaime/Plasmaar io.github.fredaime.Plasmaar1"
ID=B04200000000-BD2BC136                           # from ListDevices
$B GetButtonActions s $ID                          # the divertable buttons, their modes and actions

# haptic button (416): press → Overview
$B SetButtonAction sis $ID 416 '{"mode": "press", "press": {"component": "kwin", "action": "Overview"}}'

# gesture button (195): one action per swipe direction
$B SetButtonAction sis $ID 195 '{"mode": "gesture", "gestures": {
  "up":    {"component": "kwin", "action": "Grid View"},
  "down":  {"component": "kwin", "action": "Show Desktop"},
  "left":  {"component": "kwin", "action": "Switch One Desktop to the Left"},
  "right": {"component": "kwin", "action": "Switch One Desktop to the Right"}}}'

$B SetButtonAction sis $ID 416 '{"mode": "off"}'   # normal button again; the action is kept for later
```

Modes: `off` (normal button), `press` (an action on press), `gesture` (an action per swipe
direction, or `click` for press-and-release without moving; a pause halfway through a swipe is
fine). `GetButtonActions` lists which modes each button supports. The mode is written to the
`divert-keys` setting, so it is saved and re-applied when the device reconnects. The full
reference is in [dbus-api.md](dbus-api.md#button-actions).

`buttons.yaml` is meant to be readable and may be edited by hand:

```yaml
B04200000000-BD2BC136:
  195:
    name: Mouse Gesture Button      # informational
    mode: gesture                   # off | press | gesture
    gestures:
      up: [kwin, Grid View]         # [component, action]
      down: [kwin, Show Desktop]
  416:
    name: Haptic
    mode: press
    press: [kwin, Overview]
```

Editing `mode` in the file changes which rules run, but it does not divert the button. Use
`SetButtonAction` for that, or keep the file and `divert-keys` in step yourself. A file that
cannot be parsed is ignored and the previous mappings stay active. The next `SetButtonAction`
keeps a copy of it as `buttons.yaml.bak`.

Each mapping becomes a rule scoped to its device, for example
`[Device: BD2BC136, Key: [Haptic, pressed], KdeShortcut: [kwin, Overview]]` or
`[Device: BD2BC136, MouseGesture: [Mouse Gesture Button, Mouse Up], KdeShortcut: [kwin, Grid View]]`.
These rules run **before** `rules.yaml`. A managed mapping therefore wins over a custom rule for
the same button or gesture, and the custom rule does not run as well. Gestures and buttons
without a mapping still reach `rules.yaml`.

## Custom rules in `rules.yaml`

A button only reaches the rules once it is diverted (`SetButtonAction` with a mode does this).
Without managed actions, divert it directly. For the MX Master 4 (control ids: haptic button
416, gesture button 195):

```sh
$B SetSettingKey ssss $ID divert-keys 416 1        # haptic button: Diverted
$B SetSettingKey ssss $ID divert-keys 195 2        # gesture button: Mouse Gestures
```

`divert-keys` values: `0` Regular, `1` Diverted (press/release), `2` Mouse Gestures (press,
move, release → a direction). Set back to `0` to restore the button's normal behaviour.
The choice is saved and re-applied when the device reconnects.

```yaml
%YAML 1.3
---
- Key: [Haptic, pressed]
- KdeShortcut: [kwin, Overview]
...
---
- MouseGesture: Mouse Up
- KdeShortcut: [kwin, Grid View]
...
---
- MouseGesture: [Mouse Up, Mouse Right]
- KdeShortcut: [org.kde.spectacle.desktop, RectangularRegionScreenShot]
...
```

A gesture is matched exactly first; if that fails, repeated directions are merged, so a swipe
that pauses halfway (recorded as "up, up") still matches `Mouse Up`. Multi-step gestures such as
`[Mouse Up, Mouse Right]` keep working.

Each `---` … `...` document is one rule: its conditions, then its actions. The other Solaar
rule conditions and actions work too; see [rules.md](rules.md).

## Finding action names

`ListKdeActions` returns every component and action with its localized name, which is what
pickers use:

```sh
busctl --user --json=short call io.github.fredaime.Plasmaar /io/github/fredaime/Plasmaar \
  io.github.fredaime.Plasmaar1 ListKdeActions | jq -r '.data[0]' | jq .
```

Or ask kglobalaccel directly:

```sh
qdbus6 org.kde.kglobalaccel /component/kwin org.kde.kglobalaccel.Component.shortcutNames
qdbus6 --literal org.kde.kglobalaccel /kglobalaccel org.kde.KGlobalAccel.allComponents
```

The component is its unique name, e.g. `kwin`, `plasmashell`, `mediacontrol`,
`org.kde.spectacle.desktop`. The last part of the object path (`org_kde_spectacle_desktop`)
is accepted too. Useful KWin actions:
`Overview`, `Grid View`, `Show Desktop`, `Expose`, `Switch One Desktop to the Left/Right`,
`Window Maximize`, `Window Close`.

kglobalaccel silently ignores an unknown action name inside a valid component, so check the
spelling with `ListKdeActions` or `shortcutNames` if nothing happens. `journalctl --user -u plasmaard`
shows each `KdeShortcut action:` that runs.
