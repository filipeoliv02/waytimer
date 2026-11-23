# Waytimer

A simple activity timer with fuzzel menu integration and waybar support.

Activity and timer state are stored in `~/.local/share/waytimer/`. Updates are
written atomically and concurrent Waybar or menu invocations are serialized with
an advisory file lock. Corrupt JSON files are preserved with a timestamped
`.corrupt-*.bak` backup before they are reset.

Active durations use monotonic time, so suspends and clock changes do not alter
the timer. Session start/end timestamps remain wall-clock values for display
and history.

## Installation

Install from AUR:

```bash
paru -S waytimer
```

Build locally:

```bash
makepkg -si
```

## Waybar Integration

1. Add the waytimer module to your waybar-config.jsonc.
2. Add the CSS to your waybar style.css.
3. Example waybar config: add `"custom/waytimer"`.
4. Set a keybinding in your window manager to run `waytimer`

## Usage

- `waytimer` - Show fuzzel menu
- `waytimer waybar` - Output for waybar
- `waytimer waybar-click [button]` - Handle clicks
- `waytimer summary` - Show summary
