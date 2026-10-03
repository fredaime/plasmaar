# Mouse buttons → KDE actions

`plasmaard` runs the rules in `~/.config/plasmaar/rules.yaml` when a **diverted** button is
pressed. The `KdeShortcut` action runs any KDE global-shortcut action **by name** through
kglobalaccel — no key binding and no input injection needed. The file is reloaded
automatically when it changes.

## 1. Divert the buttons

A button only reaches the rules once it is diverted (otherwise it does its normal job).
For the MX Master 4 (control ids: haptic button 416, gesture button 195):

```sh
B="busctl --user call io.github.fredaime.Plasmaar /io/github/fredaime/Plasmaar io.github.fredaime.Plasmaar1"
ID=B04200000000-BD2BC136                           # from ListDevices
$B SetSettingKey ssss $ID divert-keys 416 1        # haptic button: Diverted
$B SetSettingKey ssss $ID divert-keys 195 2        # gesture button: Mouse Gestures
```

`divert-keys` values: `0` Regular, `1` Diverted (press/release), `2` Mouse Gestures (press,
move, release → a direction). Set back to `0` to restore the button's normal behaviour.
The choice is saved and re-applied when the device reconnects.

## 2. Map them in `rules.yaml`

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
- MouseGesture: Mouse Down
- KdeShortcut: [kwin, Show Desktop]
...
---
- MouseGesture: Mouse Left
- KdeShortcut: [kwin, Switch One Desktop to the Left]
...
---
- MouseGesture: Mouse Right
- KdeShortcut: [kwin, Switch One Desktop to the Right]
...
```

Each `---` … `...` document is one rule: its conditions, then its actions. The other Solaar
rule conditions and actions work too; see [rules.md](rules.md).

## Finding action names

```sh
qdbus6 org.kde.kglobalaccel /component/kwin org.kde.kglobalaccel.Component.shortcutNames
qdbus6 --literal org.kde.kglobalaccel /kglobalaccel org.kde.KGlobalAccel.allComponents
```

The component is the last part of the object path, e.g. `kwin`, `plasmashell`, `mediacontrol`,
`org_kde_spectacle_desktop` (`org.kde.spectacle.desktop` is accepted too). Useful KWin actions:
`Overview`, `Grid View`, `Show Desktop`, `Expose`, `Switch One Desktop to the Left/Right`,
`Window Maximize`, `Window Close`.

kglobalaccel silently ignores an unknown action name inside a valid component, so check the
spelling with `shortcutNames` if nothing happens. `journalctl --user -u plasmaard` shows each
`KdeShortcut action:` that runs.
