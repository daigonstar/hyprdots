"""The Game UI theme override (see theme_override.py): every panel becomes a classic role-playing game menu window,
a deep blue box with a thick white rounded border, and what is picked gets a small white pointer beside it. A crisp
retro font, thick light window borders and a pixel-art landscape wallpaper go with it.

An original recreation of a general style, drawn with hyprdots' own CSS. It ships no game's art, fonts, sounds or names:
the pointer (pointer.svg) and the wallpaper (make_wallpaper.py) are drawn from scratch, and the fonts are freely
licensed ones you install yourself (Terminess from ttf-terminus-nerd is in Arch's extra repo, under the OFL)."""

from __future__ import annotations

from pathlib import Path

KEY = "game"
NAME = "Game UI"
WHAT = ("Every panel a blue role-playing game menu box with a thick white border, a pointer beside what is picked, a "
        "retro font, thick light window borders and a pixel-art landscape.")

HERE = Path(__file__).resolve().parents[2] / "theme-overrides" / KEY
POINTER = HERE / "pointer.svg"  # the white menu pointer beside a picked item

# A pixel font if you have one (all free: Pixelify Sans, Silkscreen and VT323 are OFL), else Terminess (Terminus as a
# scalable font, sudo pacman -S ttf-terminus-nerd), else a plain monospace. Press Start 2P is left out on purpose:
# it is so wide that menus and the bar no longer fit.
PIXEL_LIKE = ("Pixelify Sans", "Silkscreen", "VT323", "Terminess Nerd Font Propo", "Terminess Nerd Font", "Terminus",
              "xos4 Terminus", "DejaVu Sans Mono")

# the menu window: light at the top, deep at the bottom, like the classic boxes
MENU = "linear-gradient(to bottom, #3a4fd0 0%, #2236b0 35%, #16248a 70%, #0c1662 100%)"
MENU_DEEP = "linear-gradient(to bottom, #2a3cb8 0%, #18278f 60%, #0b1458 100%)"
FRAME = "#eef1fb"  # the white border
FRAME_DIM = "#8f9ad0"  # the border of what is not in focus
GOLD = "#ffd84a"  # picked text
INK = "#05092e"  # the dark line outside the white border

VALUES = {
    "role_base": "#121e78", "role_base_text": "#ffffff", "role_surface": "#1f30a4", "role_surface_alt": "#2c42c6",
    "role_text": "#ffffff", "role_accent": GOLD, "role_secondary": "#c9d3ff", "role_muted": "#8c98d8",
    "role_icons": "#ffffff", "role_attention": "#ff6b6b",
    "base_opacity": 97, "surface_opacity": 100, "bar_style": KEY, "bar_font_size": 15,
    "gtk_colours": True, "app_font_size": 11,
}


def box(radius: int = 8, width: int = 3) -> str:
    """The menu window's frame: white border, a dark line outside it and a soft shade inside."""
    return (f"background-image: {MENU};\n    border: {width}px solid {FRAME};\n    border-radius: {radius}px;\n"
            f"    box-shadow: 0px 0px 0px 1px {INK}, inset 0px 0px 0px 1px rgba(5, 9, 46, 0.55), "
            f"inset 0px 3px 6px rgba(255, 255, 255, 0.12), 0px 4px 10px rgba(0, 0, 0, 0.45);")


def pointer(size: int = 14, room: int = 22) -> str:
    """The pointer beside a picked item: drawn in the item's left padding."""
    return (f'background-image: url("file://{POINTER}");\n    background-repeat: no-repeat;\n'
            f"    background-position: 4px center;\n    background-size: {size}px {size}px;\n    padding-left: {room}px;")


def bar_css() -> str:
    return f"""
/* Theme override: Game UI. Each part of the bar is a menu window. */
window#waybar {{
    background: none;
}}
window#waybar * {{
    color: #ffffff;
    text-shadow: 2px 2px 0px rgba(5, 9, 46, 0.9);
}}
window#waybar .modules-left, window#waybar .modules-center, window#waybar .modules-right {{
    {box(8)}
    margin: 5px 4px;
    padding: 1px 8px;
}}
window#waybar.bottom .modules-left, window#waybar.bottom .modules-center, window#waybar.bottom .modules-right {{
    margin: 4px 4px 5px 4px;
}}
window#waybar #custom-ws1.active, window#waybar #custom-ws2.active, window#waybar #custom-ws3.active,
window#waybar #custom-ws4.active, window#waybar #custom-ws5.active, window#waybar #custom-ws6.active,
window#waybar #workspaces button.active {{
    color: {GOLD};
}}
window#waybar #workspaces button.active label {{
    color: {GOLD};
}}
window#waybar #tray {{
    background: none;
    border-radius: 0px;
    box-shadow: none;
}}
window#waybar tooltip {{
    {box(6)}
}}
window#waybar tooltip label {{
    color: #ffffff;
}}
"""


def swaync_css() -> str:
    return f"""
/* Theme override: Game UI. Notifications and the centre are menu windows. */
.floating-notifications.background .notification-row .notification-background .notification,
.floating-notifications.background .notification-row .notification-background {{
    {box(8)}
    color: #ffffff;
}}
.control-center {{
    {box(10, 4)}
}}
.control-center .notification-row .notification-background .notification {{
    background-image: {MENU_DEEP};
    border: 2px solid {FRAME_DIM};
    border-radius: 6px;
    box-shadow: none;
}}
.notification-action, .control-center .notification-row .notification-background .notification .notification-action {{
    background: rgba(255, 255, 255, 0.08);
    color: #ffffff;
    border: 2px solid {FRAME_DIM};
    border-radius: 6px;
}}
.notification-action:hover {{
    border-color: {FRAME};
    color: {GOLD};
}}
label, .summary, .body, .time, .widget-title > label {{
    color: #ffffff;
    text-shadow: 1px 1px 0px rgba(5, 9, 46, 0.9);
}}
.summary {{
    color: {GOLD};
}}
"""


def tray_css() -> str:
    return f"""
/* Theme override: Game UI. The quick tray, volume pop-up and window switcher are menu windows. */
#panel, #osd, #switcher {{
    {box(10, 4)}
}}
.tile, .stat, .note, .notes-head {{
    background-image: {MENU_DEEP};
    border: 2px solid {FRAME_DIM};
    border-radius: 6px;
}}
.tile.on {{
    background-image: none;
    background-color: alpha({GOLD}, 0.22);
    border-color: {GOLD};
}}
.tile.on label {{
    color: {GOLD};
}}
.round {{
    border: 2px solid {FRAME_DIM};
}}
label {{
    text-shadow: 1px 1px 0px rgba(5, 9, 46, 0.9);
}}
"""


def launcher_css() -> str:
    return f"""
/* Theme override: Game UI. The launcher is a menu window; the picked line gets the pointer. */
.surface, .head.surface, .main.surface, .panel.surface {{
    {box(10, 4)}
}}
.rule {{ background-image: none; background-color: {FRAME_DIM}; min-height: 2px; }}
.item.selected {{
    background-color: rgba(255, 255, 255, 0.08);
    box-shadow: none;
    {pointer(14, 26)}
}}
.item.tile.selected {{
    background-image: none;
    padding-left: 6px;
    box-shadow: inset 0px 0px 0px 2px {FRAME};
}}
.cat.active {{
    background-color: rgba(255, 255, 255, 0.08);
    box-shadow: none;
    {pointer(12, 22)}
}}
.item.selected label, .item.selected .title {{ color: {GOLD}; }}
.mode {{ color: {INK}; background: {GOLD}; }}
"""


def gtk_css(version: str = "4.0") -> str:
    """GTK 3 lists pick rows as row:selected too, so one sheet serves both."""
    return f"""
/* Theme override: Game UI. Title bars are menu-window tops; picked rows get the pointer and gold text. */
headerbar, .titlebar:not(headerbar), toolbarview > .top-bar headerbar, .sidebar-pane headerbar,
.content-pane headerbar, .top-bar headerbar {{
    background-image: {MENU};
    background-color: #1a2a96;
    color: #ffffff;
    box-shadow: inset 0px -2px {FRAME_DIM};
}}
headerbar:backdrop, .titlebar:not(headerbar):backdrop, window:backdrop .top-bar headerbar {{
    background-image: {MENU_DEEP};
    color: {FRAME_DIM};
}}
headerbar .title {{
    font-weight: bold;
}}
row:selected, listview > row:selected, list > row:selected, .navigation-sidebar > row:selected {{
    background-color: rgba(255, 255, 255, 0.10);
    color: {GOLD};
    {pointer(12, 22)}
}}
row:selected label {{
    color: {GOLD};
}}
button {{
    border-radius: 6px;
}}
button:not(.flat):not(.titlebutton):not(.image-button), entry, spinbutton, dropdown > button, combobox > box > button {{
    border: 2px solid {FRAME_DIM};
}}
button:not(.flat):not(.titlebutton):not(.image-button):hover, entry:focus-within, entry:focus {{
    border-color: {FRAME};
}}
button.suggested-action {{
    background-image: {MENU};
    border: 2px solid {FRAME};
    color: {GOLD};
}}
popover > contents, popover.background > contents, menu, .menu, .context-menu {{
    background-image: {MENU};
    border: 3px solid {FRAME};
    border-radius: 8px;
}}
switch:checked {{
    background-color: {GOLD};
}}
switch:checked > slider {{
    background-color: #ffffff;
}}
"""


def hypr_config() -> dict:
    return {
        "general": {"border_size": 4, "gaps_in": 6, "gaps_out": 14,
                    "col": {"active_border": "rgb(" + FRAME[1:] + ")", "inactive_border": "rgb(" + FRAME_DIM[1:] + ")"}},
        "decoration": {"rounding": 10, "rounding_power": 2, "dim_inactive": False, "inactive_opacity": 1.0,
                       "blur": {"enabled": False},
                       "shadow": {"enabled": True, "range": 12, "render_power": 3, "color": "rgba(05092ecc)",
                                  "color_inactive": "rgba(05092e77)"}},
    }
