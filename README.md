# Waytimer

A simple activity timer with fuzzel menu integration and waybar support.

## Installation

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
