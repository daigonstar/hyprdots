"""The Sci-fi HUD theme override (see theme_override.py): dark glass panels edged in thin cyan lines with bracket corners,
a technical font, and a few things that move: window borders whose gradient slowly turns, a scan line that sweeps
along the bar as it starts, the active workspace and picked items pulsing gently, and panels that switch on with a short flicker.

An original style drawn with hyprdots' own CSS. It copies no film's or game's interface, art or names: the wallpaper
(make_wallpaper.py) is drawn from scratch and the fonts are free ones you install yourself.

What moves keeps redrawing that part of the screen while it moves. Only small things loop (the active workspace's glow,
and Hyprland turning the border gradient); the rest runs once, when the bar starts, a panel opens or an item is picked."""

from __future__ import annotations

KEY = "scifi"
NAME = "Sci-fi HUD"
WHAT = ("Dark glass panels in thin cyan lines with bracket corners, a technical font, window borders whose colours "
        "slowly turn, a glowing workspace marker and panels that flicker on.")

# A display font if you have one (all free: Orbitron, Oxanium, Exo 2 and Share Tech Mono are OFL), else Iosevka
# (sudo pacman -S ttc-iosevka), else the bar's usual Nerd Font, which every hyprdots install has
TECH_LIKE = ("Orbitron", "Oxanium", "Exo 2", "Share Tech Mono", "Iosevka Aile", "Iosevka",
             "CaskaydiaCove Nerd Font Propo", "DejaVu Sans Mono")

CYAN = "#00e5ff"
CYAN_DIM = "rgba(0, 229, 255, 0.35)"
VIOLET = "#7c4dff"
GLASS = "rgba(5, 14, 26, 0.92)"
GLASS_DEEP = "rgba(3, 9, 18, 0.96)"
TEXT = "#c8f7ff"
ALERT = "#ff3d71"

VALUES = {
    "role_base": "#07111d", "role_base_text": TEXT, "role_surface": "#0b1d2e", "role_surface_alt": "#10304a",
    "role_text": TEXT, "role_accent": CYAN, "role_secondary": "#7fdcff", "role_muted": "#3f7f92",
    "role_icons": CYAN, "role_attention": ALERT,
    "base_opacity": 92, "surface_opacity": 85, "bar_style": KEY, "bar_font_size": 14,
    "gtk_colours": True, "app_font_size": 10,
}


def brackets(base: str = GLASS, colour: str = CYAN, length: int = 12, width: int = 2) -> str:
    """A HUD frame: bracket corners in colour over a flat panel, drawn as layered backgrounds."""
    line = f"linear-gradient({colour}, {colour})"
    sizes = [f"{length}px {width}px", f"{width}px {length}px"] * 4
    spots = ["left top", "left top", "right top", "right top", "left bottom", "left bottom", "right bottom", "right bottom"]
    return (f"background-color: transparent;\n"
            f"    background-image: {', '.join([line] * 8)}, linear-gradient({base}, {base});\n"
            f"    background-size: {', '.join(sizes)}, 100% 100%;\n"
            f"    background-position: {', '.join(spots)}, left top;\n"
            f"    background-repeat: no-repeat;\n"
            f"    border: 1px solid {CYAN_DIM};")


GLOW = f"0px 0px 10px rgba(0, 229, 255, 0.18), inset 0px 0px 14px rgba(0, 229, 255, 0.06)"

# one-shot: a panel switching on, with a short flicker
BOOT = """
@keyframes hd-boot {
    0% { opacity: 0.0; }
    18% { opacity: 0.85; }
    26% { opacity: 0.35; }
    40% { opacity: 1.0; }
    100% { opacity: 1.0; }
}
"""
# always on, small: a soft glow breathing in and out
PULSE = """
@keyframes hd-pulse {
    0% { text-shadow: 0px 0px 2px rgba(0, 229, 255, 0.35); }
    100% { text-shadow: 0px 0px 9px rgba(0, 229, 255, 0.95); }
}
"""


def bar_css() -> str:
    return BOOT + PULSE + f"""
/* Theme override: Sci-fi HUD. Each part of the bar is a bracketed glass panel; a scan line sweeps along the
   bottom once, as the bar starts (looping, it kept the bar redrawing: about 6% of a core). */
@keyframes hd-scan {{
    0% {{ background-position: -40% 100%; }}
    45% {{ background-position: 140% 100%; }}
    100% {{ background-position: 140% 100%; }}
}}
window#waybar {{
    background-color: transparent;
    background-image: linear-gradient(to right, transparent, rgba(0, 229, 255, 0.0) 30%, {CYAN} 50%, rgba(0, 229, 255, 0.0) 70%, transparent);
    background-size: 30% 1px;
    background-position: -40% 100%;
    background-repeat: no-repeat;
    animation: hd-scan 1400ms ease-in-out 1;
}}
window#waybar * {{
    color: {TEXT};
    text-shadow: none;
}}
window#waybar .modules-left, window#waybar .modules-center, window#waybar .modules-right {{
    {brackets()}
    border-radius: 2px;
    box-shadow: {GLOW};
    margin: 5px 4px;
    padding: 0px 10px;
    animation: hd-boot 700ms ease-out;
}}
window#waybar #custom-ws1.active, window#waybar #custom-ws2.active, window#waybar #custom-ws3.active,
window#waybar #custom-ws4.active, window#waybar #custom-ws5.active, window#waybar #custom-ws6.active,
window#waybar #workspaces button.active label {{
    color: {CYAN};
    animation: hd-pulse 1.8s ease-in-out infinite alternate;
}}
window#waybar #clock {{
    color: {CYAN};
    letter-spacing: 1px;
}}
window#waybar #tray {{
    background: none;
    border-radius: 0px;
    box-shadow: none;
}}
window#waybar tooltip {{
    {brackets(GLASS_DEEP)}
    border-radius: 2px;
}}
"""


def swaync_css() -> str:
    return BOOT + f"""
/* Theme override: Sci-fi HUD. Notifications switch on with a flicker; the centre is a bracketed console. */
.floating-notifications.background .notification-row .notification-background .notification,
.floating-notifications.background .notification-row .notification-background {{
    {brackets()}
    border-radius: 2px;
    box-shadow: {GLOW};
    color: {TEXT};
    animation: hd-boot 600ms ease-out;
}}
.control-center {{
    {brackets(GLASS_DEEP, CYAN, 18)}
    border-radius: 2px;
    box-shadow: {GLOW};
    animation: hd-boot 500ms ease-out;
}}
.control-center .notification-row .notification-background .notification {{
    background: rgba(0, 229, 255, 0.04);
    border: 1px solid {CYAN_DIM};
    border-radius: 2px;
    box-shadow: none;
}}
.notification-action, .control-center .notification-row .notification-background .notification .notification-action {{
    background: rgba(0, 229, 255, 0.06);
    color: {CYAN};
    border: 1px solid {CYAN_DIM};
    border-radius: 2px;
}}
.notification-action:hover {{
    background: rgba(0, 229, 255, 0.18);
    border-color: {CYAN};
}}
label, .summary, .body, .time, .widget-title > label {{
    color: {TEXT};
    text-shadow: none;
}}
.summary {{
    color: {CYAN};
    letter-spacing: 1px;
}}
.critical .summary {{
    color: {ALERT};
}}
"""


def tray_css() -> str:
    return BOOT + f"""
/* Theme override: Sci-fi HUD. The quick tray, volume pop-up and window switcher are bracketed consoles. */
#panel, #osd, #switcher {{
    {brackets(GLASS_DEEP, CYAN, 18)}
    border-radius: 2px;
    box-shadow: {GLOW};
    animation: hd-boot 500ms ease-out;
}}
.tile, .stat, .note, .notes-head, .round {{
    background: rgba(0, 229, 255, 0.05);
    border: 1px solid {CYAN_DIM};
    border-radius: 2px;
}}
.tile.on {{
    background: rgba(0, 229, 255, 0.20);
    border-color: {CYAN};
    box-shadow: 0px 0px 8px rgba(0, 229, 255, 0.35);
}}
.tile.on label {{
    color: {CYAN};
}}
"""


def launcher_css() -> str:
    return BOOT + f"""
/* Theme override: Sci-fi HUD. The launcher is a bracketed console that flickers on; the picked line lights up. */
@keyframes hd-pick {{
    0% {{ box-shadow: inset 3px 0px 0px {CYAN}, 0px 0px 0px rgba(0, 229, 255, 0.0); }}
    100% {{ box-shadow: inset 3px 0px 0px {CYAN}, 0px 0px 12px rgba(0, 229, 255, 0.35); }}
}}
.surface, .head.surface, .main.surface, .panel.surface {{
    {brackets(GLASS_DEEP, CYAN, 18)}
    border-radius: 2px;
    box-shadow: {GLOW}, 0px 18px 50px rgba(0, 0, 0, 0.55);
    animation: hd-boot 450ms ease-out;
}}
.rule {{ background-image: none; background-color: {CYAN_DIM}; min-height: 1px; }}
.item {{ border-radius: 2px; }}
.item.selected {{
    background-color: rgba(0, 229, 255, 0.10);
    animation: hd-pick 1.4s ease-in-out infinite alternate;
}}
.item.tile.selected {{
    box-shadow: inset 0px 0px 0px 1px {CYAN};
    animation: none;
}}
.item.selected label, .item.selected .title {{ color: {CYAN}; }}
.cat.active {{ background-color: rgba(0, 229, 255, 0.10); box-shadow: inset 3px 0px 0px {CYAN}; }}
.cat.active label {{ color: {CYAN}; }}
.mode {{ color: #02070d; background: {CYAN}; border-radius: 2px; }}
"""


def gtk_css(version: str = "4.0") -> str:
    """Apps keep to one-shot movement: a picked row lights up once, popovers flicker on. Nothing loops in apps."""
    return f"""
/* Theme override: Sci-fi HUD. Dark glass title bars with a cyan rule; picked rows light up; corners are near square. */
@keyframes hd-row {{
    0% {{ background-color: rgba(0, 229, 255, 0.30); }}
    100% {{ background-color: rgba(0, 229, 255, 0.10); }}
}}
@keyframes hd-on {{
    0% {{ opacity: 0.0; }}
    30% {{ opacity: 0.9; }}
    45% {{ opacity: 0.5; }}
    100% {{ opacity: 1.0; }}
}}
headerbar, .titlebar:not(headerbar), toolbarview > .top-bar headerbar, .sidebar-pane headerbar,
.content-pane headerbar, .top-bar headerbar {{
    background-color: #050e1a;
    background-image: none;
    color: {TEXT};
    box-shadow: inset 0px -1px {CYAN_DIM};
}}
headerbar .title {{
    color: {CYAN};
    letter-spacing: 1px;
}}
row:selected, listview > row:selected, list > row:selected, .navigation-sidebar > row:selected {{
    background-color: rgba(0, 229, 255, 0.10);
    box-shadow: inset 3px 0px 0px {CYAN};
    color: {CYAN};
    animation: hd-row 450ms ease-out;
}}
row:selected label {{
    color: {CYAN};
}}
button, entry, spinbutton, .card, popover > contents {{
    border-radius: 3px;
}}
button:not(.flat):not(.titlebutton):not(.image-button), entry, spinbutton {{
    box-shadow: inset 0px 0px 0px 1px {CYAN_DIM};
}}
button:not(.flat):not(.titlebutton):not(.image-button):hover, entry:focus-within {{
    box-shadow: inset 0px 0px 0px 1px {CYAN}, 0px 0px 6px rgba(0, 229, 255, 0.3);
}}
button.suggested-action {{
    background-color: rgba(0, 229, 255, 0.18);
    color: {CYAN};
    box-shadow: inset 0px 0px 0px 1px {CYAN};
}}
popover > contents, popover.background > contents, menu, .menu, .context-menu {{
    background-color: {GLASS_DEEP};
    box-shadow: inset 0px 0px 0px 1px {CYAN_DIM}, 0px 6px 18px rgba(0, 0, 0, 0.5);
    animation: hd-on 260ms ease-out;
}}
switch:checked {{
    background-color: {CYAN};
}}
"""


def hypr_config() -> dict:
    """Thin borders in a cyan to violet gradient (turned slowly by ANIMATIONS), near-square corners, a cyan glow."""
    return {
        "general": {"border_size": 2, "gaps_in": 6, "gaps_out": 12,
                    "col": {"active_border": {"colors": ["rgba(00e5ffff)", "rgba(7c4dffff)", "rgba(00e5ffff)"], "angle": 45},
                            "inactive_border": "rgba(00e5ff33)"}},
        "decoration": {"rounding": 4, "rounding_power": 2, "dim_inactive": False, "inactive_opacity": 1.0,
                       "blur": {"enabled": False},
                       "shadow": {"enabled": True, "range": 14, "render_power": 3, "color": "rgba(00e5ff44)",
                                  "color_inactive": "rgba(00000055)"}},
    }


# Hyprland's own movement: the active border's gradient turns once a minute, and windows open with a quick zoom.
# hyprland.lua applies these after window.lua's; leaving the look reloads window.lua's own.
CURVES = {"hd_snap": [[0.2, 0.9], [0.1, 1.05]]}
ANIMATIONS = [
    {"leaf": "borderangle", "enabled": True, "speed": 100, "bezier": "linear", "style": "loop"},
    {"leaf": "windowsIn", "enabled": True, "speed": 3, "bezier": "hd_snap", "style": "popin 70%"},
    {"leaf": "layersIn", "enabled": True, "speed": 2.5, "bezier": "hd_snap", "style": "fade"},
]
