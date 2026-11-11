"""The Mac style theme override (see theme_override.py): a light, translucent menu bar along the top, a dock of open
apps along the bottom, round red, yellow and green window buttons on the left, soft shadows, rounded corners and a
smooth gradient wallpaper.

An original recreation drawn with hyprdots' own CSS. It ships none of Apple's assets: no logo (the menu bar shows your
Super key logo from settings > Hyprdots), no San Francisco font (its licence only covers Apple's own systems; Inter
is a free font of the same kind, and Adwaita Sans is made from it), no icons and no wallpapers."""

from __future__ import annotations

KEY = "mac"
NAME = "Mac style"
WHAT = ("A light menu bar along the top, a dock of open apps along the bottom, round red, yellow and green window "
        "buttons, soft shadows and a smooth gradient wallpaper.")

# Inter if you have it (sudo pacman -S inter-font), else Adwaita Sans, which GNOME made from Inter
INTER_LIKE = ("Inter", "Inter Variable", "Adwaita Sans", "Cantarell", "Liberation Sans")

VALUES = {
    "role_base": "#f5f5f7", "role_base_text": "#1d1d1f", "role_surface": "#f6f6f6", "role_surface_alt": "#ffffff",
    "role_text": "#1d1d1f", "role_accent": "#007aff", "role_secondary": "#3c3c43", "role_muted": "#8e8e93",
    "role_icons": "#1d1d1f", "role_attention": "#ff3b30",
    "base_opacity": 88, "surface_opacity": 72, "bar_style": "mac", "bar_font_size": 13,
    "gtk_colours": True, "app_font_size": 10,
}

LAUNCHER_STYLE = "spotlight"  # Super+Space: a search pill in the middle of the screen
LAUNCHPAD = "~/.config/hypr/launcher/launcher.sh --style grid"  # the dock's grid button: every app, full screen
LOGO_MENU = "~/.config/hypr/launcher/launcher.sh --logo-menu"  # logomenu.py: About this PC, Settings, Force quit...
BUTTON_LAYOUT = "close,minimize,maximize:appmenu"  # window buttons on the left, in this order
DOCK_GAP = 6  # px between the dock and the bottom of the screen

GLASS = "rgba(246, 246, 246, 0.72)"
EDGE = "rgba(255, 255, 255, 0.55)"


def bar_css() -> str:
    return f"""
/* Theme override: Mac style menu bar (the dock is drawn by waybar/scripts/dock.py) */
window#waybar.menubar {{
    background: {GLASS};
    border-bottom: 1px solid rgba(0, 0, 0, 0.08);
}}
window#waybar.menubar * {{
    color: #1d1d1f;
    text-shadow: none;
}}
window#waybar.menubar #custom-menu-logo {{
    font-size: 16px;
    padding: 0px 12px 0px 16px;
}}
window#waybar.menubar #window {{
    font-weight: bold;
    padding: 0px 8px;
}}
window#waybar.menubar #clock {{
    padding: 0px 14px 0px 8px;
}}
window#waybar.menubar #tray {{
    background: none;
    border-radius: 0px;
    box-shadow: none;
}}
"""


def bar(logo: str) -> dict:
    """The menu bar (laid over your layout) and the dock's settings. The dock is drawn by hyprdots itself
    (waybar/scripts/dock.py, from the config.dock.json barlayout writes), so it can rise and sink like a Mac's."""
    return {
        "name": "menubar", "position": "top", "height": 26, "spacing": 4,
        "modules-left": ["custom/menu-logo", "hyprland/window"],
        "modules-center": [],
        "modules-right": ["custom/updates", "tray", "pulseaudio", "battery", "custom/recording", "custom/noti", "clock"],
        "custom/menu-logo": {"format": logo or "\U000f0035", "tooltip-format": "About this PC, settings, force quit, sleep, restart, shut down",
                             "on-click": LOGO_MENU},
        "hyprland/window": {"format": "{title:.60}", "separate-outputs": True},
        "clock": {"format": "{:%a %d %b  %H:%M}"},
        "tray": {"icon-size": 15, "spacing": 8},
        "dock": {"icon-size": 48, "margin-bottom": DOCK_GAP, "launchpad": LAUNCHPAD},  # drawn by waybar/scripts/dock.py
    }


def swaync_css() -> str:
    return """
/* Theme override: Mac style. Rounded, frosted notifications and centre. */
.floating-notifications.background .notification-row .notification-background .notification,
.floating-notifications.background .notification-row .notification-background {
    background: rgba(246, 246, 246, 0.96);
    color: #1d1d1f;
    border: 1px solid rgba(0, 0, 0, 0.08);
    border-radius: 16px;
    box-shadow: 0px 6px 20px rgba(0, 0, 0, 0.18);
}
.control-center {
    background: rgba(246, 246, 246, 0.95);
    border: 1px solid rgba(255, 255, 255, 0.6);
    border-radius: 18px;
}
.control-center .notification-row .notification-background .notification {
    background: rgba(255, 255, 255, 0.7);
    border: none;
    border-radius: 14px;
}
.notification-action, .control-center .notification-row .notification-background .notification .notification-action {
    background: rgba(0, 0, 0, 0.06);
    color: #1d1d1f;
    border: none;
    border-radius: 8px;
}
label, .summary, .body, .time, .widget-title > label {
    color: #1d1d1f;
    text-shadow: none;
}
"""


def launcher_css() -> str:
    return """
/* Theme override: Mac style search */
.surface, .head.surface, .main.surface {
    background-color: rgba(246, 246, 246, 0.96);
    background-image: none;
    border: 1px solid rgba(255, 255, 255, 0.6);
    border-radius: 14px;
    box-shadow: 0px 20px 60px rgba(0, 0, 0, 0.35);
}
.rule { background-image: none; min-height: 0px; }
.item.selected { background: #007aff; box-shadow: none; }
.item.selected label, .item.selected .title, .item.selected .tail { color: #ffffff; opacity: 1; }
.mode { color: #ffffff; background: #007aff; }
"""


def gtk_css(version: str = "4.0") -> str:
    """GTK 3 has no -gtk-icon-size and no windowcontrols: its title bar buttons are .titlebutton."""
    css = _GTK
    if version.startswith("3"):
        css = css.replace("    -gtk-icon-size: 8px;\n", "") + _GTK3_BUTTONS
    return css


_GTK3_BUTTONS = """
headerbar button.titlebutton {
    min-width: 14px; min-height: 14px; padding: 0px; margin: 0px 3px;
    border: none; border-radius: 99px; box-shadow: inset 0px 0px 0px 1px rgba(0, 0, 0, 0.12);
    background-image: none; color: transparent;
}
headerbar button.titlebutton.close { background-color: #ff5f57; }
headerbar button.titlebutton.minimize { background-color: #febc2e; }
headerbar button.titlebutton.maximize { background-color: #28c840; }
headerbar:hover button.titlebutton { color: rgba(0, 0, 0, 0.55); }
"""

_GTK = """
/* Theme override: Mac style. Light title bars, round window buttons, blue for what is picked, green switches. */
headerbar, .titlebar:not(headerbar), toolbarview > .top-bar headerbar, .sidebar-pane headerbar,
.content-pane headerbar, .top-bar headerbar {
    background-color: #ececec;
    background-image: none;
    color: #1d1d1f;
    box-shadow: inset 0px -1px rgba(0, 0, 0, 0.09);
}
headerbar:backdrop, .titlebar:not(headerbar):backdrop, window:backdrop .top-bar headerbar {
    background-color: #f6f6f6;
    color: #9a9a9a;
}
headerbar .title {
    font-weight: bold;
}
windowcontrols {
    margin: 0px 4px;
}
windowcontrols button {
    min-width: 20px;
    min-height: 20px;
    padding: 0px;
    margin: 0px 1px;
    border: none;
    background: none;
    box-shadow: none;
}
windowcontrols button > image {
    padding: 3px;
    -gtk-icon-size: 8px;
    border-radius: 99px;
    color: transparent;
    box-shadow: inset 0px 0px 0px 1px rgba(0, 0, 0, 0.12);
}
windowcontrols button.close > image { background-color: #ff5f57; }
windowcontrols button.minimize > image { background-color: #febc2e; }
windowcontrols button.maximize > image { background-color: #28c840; }
windowcontrols:hover button > image { color: rgba(0, 0, 0, 0.55); }
window:backdrop windowcontrols button > image { background-color: #d8d8d8; }
button {
    border-radius: 6px;
}
button.suggested-action {
    background-color: #007aff;
    color: #ffffff;
}
entry, spinbutton {
    border-radius: 6px;
}
switch:checked {
    background-color: #34c759;
}
"""


def hypr_config() -> dict:
    return {
        "general": {"border_size": 1, "gaps_in": 6, "gaps_out": 12,
                    "col": {"active_border": "rgba(0000002e)", "inactive_border": "rgba(0000001a)"}},
        "decoration": {"rounding": 12, "rounding_power": 3, "dim_inactive": False, "inactive_opacity": 1.0,
                       "blur": {"enabled": True, "size": 10, "passes": 3, "vibrancy": 0.2},
                       "shadow": {"enabled": True, "range": 28, "render_power": 4, "color": "rgba(00000044)",
                                  "color_inactive": "rgba(00000022)"}},
    }


# the frosted glass: the menu bar, dock, notifications and search are see-through, so blur what is behind them
LAYER_RULES = [
    {"name": "mac-style-glass-bar", "match": {"namespace": "^(menubar|dock)$"}, "blur": True, "ignore_alpha": 0.2},
    {"name": "mac-style-glass-notifications", "match": {"namespace": "^swaync-(notification-window|control-center)$"},
     "blur": True, "ignore_alpha": 0.2},
    {"name": "mac-style-glass-launcher", "match": {"namespace": "^(launcher|logomenu)$"}, "blur": True, "ignore_alpha": 0.5},
]
