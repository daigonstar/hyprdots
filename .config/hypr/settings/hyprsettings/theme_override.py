"""Theme overrides (Theme page): one-click looks that restyle the whole desktop at once.

An override never changes your own Theme page settings. It is one setting, [theme] override, and while it names a look,
design.theme_options() lays that look's values over yours, so every part of the desktop that is built from the Theme
page (the bar, notifications, the quick tray, rofi, the launcher, window borders, the lock screen, GTK and Qt apps,
the settings window) follows it with no code of its own. Each look can also add:

- extra CSS for a part (extra()), written inside that part's generated block, so it goes when the override does
- Hyprland options (hypr_config()), written to theme.lua and applied by hyprland.lua after your Hyprland page
  settings, so the override wins while it is on and your own values return the moment it is off
- its own bar (bar()): position, modules and their definitions, laid over your Bar layout in config.generated.json
- a wallpaper, set when you switch to the look; the wallpaper you had is remembered and put back when you switch to
  None (unless you picked another one in the meantime)

Role colours in a look are #hex rather than palette slots, so a look stays the same whatever the wallpaper is.

The XP style ("luna") is an original recreation: its CSS, colours and wallpaper were made for hyprdots. It ships none
of Microsoft's assets (no photo, logo, icons, sounds or fonts)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from . import look_game, look_mac, look_scifi

NONE = "none"
LOOKS = (
    (NONE, "None", "Your own settings below, following the wallpaper."),
    ("luna", "XP style", "A blue taskbar along the bottom with a green start button, beige windows with blue title "
                         "bars, a Tahoma-like font and a green hill under a blue sky."),
    (look_mac.KEY, look_mac.NAME, look_mac.WHAT),
    (look_game.KEY, look_game.NAME, look_game.WHAT),
    (look_scifi.KEY, look_scifi.NAME, look_scifi.WHAT),
)
CHOICES = tuple((key, name) for key, name, _what in LOOKS)
HERE = Path(__file__).resolve().parents[2] / "theme-overrides"  # hypr/theme-overrides: each look's files

# A font close to Tahoma: your own Tahoma if you have one, else DejaVu Sans Condensed (free, from the same family of
# designs as Verdana), else whatever plain sans-serif is installed
TAHOMA_LIKE = ("Tahoma", "DejaVu Sans Condensed", "DejaVu Sans", "Liberation Sans", "FreeSans", "Adwaita Sans")

# ---- XP style (Luna) colours ------------------------------------------------------------------------------------------
TASKBAR = ("linear-gradient(to bottom, #3f8cf3 0%, #245edb 9%, #2257d5 45%, #2152cf 88%, #1941a5 100%)")
START = ("linear-gradient(to bottom, #3c9b3c 0%, #4fb94f 12%, #3a9c3a 45%, #2f8b2f 85%, #276f27 100%)")
START_HOVER = ("linear-gradient(to bottom, #5cc85c 0%, #7fe07f 12%, #58c458 45%, #43ad43 85%, #368a36 100%)")
START_DOWN = ("linear-gradient(to bottom, #1f6b1f 0%, #2a7f2a 15%, #328f32 55%, #2c822c 90%, #236b23 100%)")
TRAY = ("linear-gradient(to bottom, #0c59b9 0%, #139ee9 6%, #18b5f2 12%, #139beb 40%, #1290e8 80%, #0d8dea 95%, #0c59b9 100%)")
TITLE = ("linear-gradient(to bottom, #0997ff 0%, #0053ee 8%, #0050ee 40%, #0066ff 88%, #0058e6 93%, #003dd7 100%)")
TITLE_BACKDROP = ("linear-gradient(to bottom, #a8c1f2 0%, #7b9be6 8%, #7896e0 40%, #8aa7ea 88%, #7e9ae0 100%)")
BUTTON = "linear-gradient(to bottom, #ffffff 0%, #f4f3ee 70%, #e3e0d6 92%, #d6d0c5 100%)"
BUTTON_DOWN = "linear-gradient(to bottom, #d6d2c2 0%, #e5e3da 20%, #f2f1ea 100%)"

LUNA = {
    "role_base": "#ece9d8", "role_base_text": "#000000", "role_surface": "#245edb", "role_surface_alt": "#1290e8",
    "role_text": "#ffffff", "role_accent": "#316ac5", "role_secondary": "#d6e4fb", "role_muted": "#7a96df",
    "role_icons": "#ffffff", "role_attention": "#f8b330",
    "base_opacity": 100, "surface_opacity": 100, "bar_style": "luna", "bar_font_size": 13,
    "gtk_colours": True, "app_font_size": 10,
}
# window borders: the blue of an active title bar, the faded blue of an inactive one
LUNA_BORDER, LUNA_BORDER_INACTIVE = "#0055e5", "#7a96df"


# ---- reading -------------------------------------------------------------------------------------------------------
def active(o: dict) -> str:
    key = str(o.get("override", NONE))
    return key if key in dict(CHOICES) else NONE


def values(key: str) -> dict:
    """What the look lays over your Theme page settings (empty for None)."""
    if key == "luna":
        font = first_installed(TAHOMA_LIKE)
        return {**LUNA, "bar_font": font, "app_font": font}
    if key == look_mac.KEY:
        font = first_installed(look_mac.INTER_LIKE)
        return {**look_mac.VALUES, "bar_font": font, "app_font": font}
    if key == look_game.KEY:
        font = first_installed(look_game.PIXEL_LIKE)
        return {**look_game.VALUES, "bar_font": font, "app_font": font}
    if key == look_scifi.KEY:
        font = first_installed(look_scifi.TECH_LIKE)
        return {**look_scifi.VALUES, "bar_font": font, "app_font": font}
    return {}


def launcher_style(o: dict) -> str | None:
    """What Super+Space opens under the look: "startmenu" (XP style's own menu), a launcher style, or None for the
    one picked on the Launcher page."""
    return {"luna": "startmenu", look_mac.KEY: look_mac.LAUNCHER_STYLE}.get(active(o))


# Where the window buttons sit, in GNOME's button-layout form (GTK apps read it). None leaves yours alone.
BUTTON_LAYOUTS = {"luna": "appmenu:minimize,maximize,close", look_mac.KEY: look_mac.BUTTON_LAYOUT}


def apply(o: dict) -> dict:
    """Your Theme page options with the active look laid over them."""
    return {**o, **values(active(o))}


_families: set[str] | None = None


def installed_families() -> set[str]:
    """Every family name fontconfig knows, including the second names a font lists (DejaVu Sans Condensed)."""
    global _families
    if _families is None:
        try:
            out = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        _families = {name.strip() for line in out.splitlines() for name in line.split(",") if name.strip()}
    return _families


def first_installed(candidates: tuple[str, ...]) -> str:
    have = installed_families()
    return next((name for name in candidates if name in have), candidates[-1])


def wallpaper(key: str, chosen: str = "") -> Path | None:
    """The look's wallpaper: your own picture when you chose one and it is still there, else the built-in one."""
    if key == NONE:
        return None
    mine = Path(os.path.expanduser(str(chosen))) if str(chosen).strip() else None
    if mine is not None and mine.is_file():
        return mine
    path = HERE / key / "wallpaper.jpg"
    return path if path.exists() else None


# ---- what each part adds ---------------------------------------------------------------------------------------------
def extra(o: dict, part: str) -> str:
    """Extra CSS for one part: bar, swaync, tray, gtk3, gtk4, launcher, settings. Empty without an override."""
    if active(o) == look_mac.KEY:
        return {"bar": look_mac.bar_css, "swaync": look_mac.swaync_css, "gtk3": lambda: look_mac.gtk_css("3.0"),
                "gtk4": look_mac.gtk_css, "launcher": look_mac.launcher_css}.get(part, lambda: "")()
    if active(o) == look_game.KEY:
        return {"bar": look_game.bar_css, "swaync": look_game.swaync_css, "tray": look_game.tray_css,
                "gtk3": lambda: look_game.gtk_css("3.0"), "gtk4": look_game.gtk_css,
                "launcher": look_game.launcher_css}.get(part, lambda: "")()
    if active(o) == look_scifi.KEY:
        return {"bar": look_scifi.bar_css, "swaync": look_scifi.swaync_css, "tray": look_scifi.tray_css,
                "gtk3": lambda: look_scifi.gtk_css("3.0"), "gtk4": look_scifi.gtk_css,
                "launcher": look_scifi.launcher_css}.get(part, lambda: "")()
    if active(o) != "luna":
        return ""
    return {"bar": _luna_bar, "swaync": _luna_swaync, "gtk3": _luna_gtk, "gtk4": _luna_gtk,
            "launcher": _luna_launcher, "settings": _luna_gtk}.get(part, lambda: "")()


def _luna_bar() -> str:
    return f"""
/* Theme override: XP style taskbar */
window#waybar {{
    background-image: {TASKBAR};
    border-top: 1px solid #0c3daa;
}}
window#waybar * {{
    text-shadow: none;
}}
window#waybar .modules-left, window#waybar .modules-center {{
    padding: 0px;
}}
window#waybar .modules-right {{
    background-image: {TRAY};
    border-left: 1px solid #0c4fb8;
    box-shadow: inset 1px 0px #19b9f3;
    padding: 0px 4px 0px 6px;
    margin: 0px;
}}
window#waybar #custom-start {{
    background-image: {START};
    color: #ffffff;
    font-size: 17px;
    font-weight: bold;
    font-style: italic;
    padding: 0px 22px 0px 12px;
    margin: 0px 10px 0px 0px;
    border-radius: 0px 12px 12px 0px;
    box-shadow: inset -2px 0px 3px rgba(0, 0, 0, 0.35), inset 0px 1px rgba(255, 255, 255, 0.35);
    text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.6);
    transition: background-image 180ms ease-out, box-shadow 180ms ease-out, padding 120ms ease-out;
}}
window#waybar #startbutton:hover #custom-start {{
    background-image: {START_HOVER};
    box-shadow: inset -2px 0px 3px rgba(0, 0, 0, 0.3), inset 0px 1px rgba(255, 255, 255, 0.55),
                0px 0px 8px rgba(150, 255, 150, 0.55);
}}
window#waybar #custom-start.open {{
    background-image: {START_DOWN};
    box-shadow: inset 2px 2px 5px rgba(0, 0, 0, 0.55), inset -1px -1px rgba(255, 255, 255, 0.15);
    padding: 2px 21px 0px 13px;
}}
window#waybar #startbutton:hover #custom-start.open {{
    background-image: {START_DOWN};
}}
window#waybar #taskbar {{
    padding: 0px 4px;
}}
window#waybar #taskbar button {{
    all: unset;
    background-image: linear-gradient(to bottom, #3c8af5 0%, #3880f0 10%, #2f6fe6 90%, #1f58d0 100%);
    border: 1px solid #1a4cbb;
    border-radius: 3px;
    box-shadow: inset 1px 1px rgba(255, 255, 255, 0.25);
    margin: 3px 2px;
    padding: 0px 8px;
    min-width: 150px;
    color: #ffffff;
}}
window#waybar #taskbar button:hover {{
    background-image: linear-gradient(to bottom, #53a0ff 0%, #4a92fb 10%, #3d80f2 90%, #2b65db 100%);
}}
window#waybar #taskbar button.active {{
    background-image: linear-gradient(to bottom, #1747a8 0%, #1e52bd 15%, #1e54c3 100%);
    border-color: #0f3a99;
    box-shadow: inset 1px 1px 2px rgba(0, 0, 0, 0.45);
}}
window#waybar #taskbar button label {{
    color: #ffffff;
}}
window#waybar #clock {{
    color: #ffffff;
    padding: 0px 8px 0px 6px;
}}
window#waybar #tray {{
    background: none;
    border-radius: 0px;
    box-shadow: none;
}}
window#waybar #workspaces button, window#waybar #custom-ws1, window#waybar #custom-ws2, window#waybar #custom-ws3,
window#waybar #custom-ws4, window#waybar #custom-ws5, window#waybar #custom-ws6 {{
    padding: 0px 4px;
    text-shadow: none;
}}
"""


def _luna_swaync() -> str:
    return """
/* Theme override: XP style. Pop-up notifications are pale yellow balloons; the centre is a beige window. */
.floating-notifications.background .notification-row .notification-background .notification,
.floating-notifications.background .notification-row .notification-background {
    background: #ffffe1;
    color: #000000;
    border: 1px solid #000000;
    border-radius: 8px;
    box-shadow: 2px 3px 6px rgba(0, 0, 0, 0.35);
}
.control-center {
    background: #ece9d8;
    border: 3px solid #0055e5;
    border-radius: 8px 8px 0px 0px;
}
.control-center .notification-row .notification-background .notification {
    background: #ffffff;
    border: 1px solid #7f9db9;
    border-radius: 3px;
}
.notification-action, .control-center .notification-row .notification-background .notification .notification-action {
    background: #f4f3ee;
    color: #000000;
    border: 1px solid #003c74;
    border-radius: 3px;
}
label, .summary, .body, .time, .widget-title > label {
    color: #000000;
    text-shadow: none;
}
"""


def _luna_launcher() -> str:
    return """
/* Theme override: XP style menu */
.surface {
    background-color: #ffffff;
    background-image: none;
    border: 2px solid #0055e5;
    border-radius: 8px 8px 3px 3px;
    box-shadow: 2px 4px 14px rgba(0, 0, 0, 0.5);
}
.sidebar { background: #d3e5fa; border-right: 1px solid #95bdee; }
.rule { background-image: linear-gradient(90deg, transparent, #f8a33c 20%, #f8a33c 80%, transparent); }
.item.selected, .cat.active { background: #316ac5; box-shadow: none; }
.item.selected label, .item.selected .title, .cat.active label { color: #ffffff; }
.mode { color: #ffffff; background: #316ac5; }
"""


def _luna_gtk() -> str:
    return f"""
/* Theme override: XP style. Title bars are blue, buttons are pale with a dark blue edge. */
headerbar, .titlebar:not(headerbar), toolbarview > .top-bar headerbar, .sidebar-pane headerbar,
.content-pane headerbar, .top-bar headerbar {{
    background-color: #0055e5;
    background-image: {TITLE};
    color: #ffffff;
    box-shadow: none;
}}
headerbar:backdrop, .titlebar:not(headerbar):backdrop, window:backdrop .top-bar headerbar {{
    background-image: {TITLE_BACKDROP};
    color: #e8eefb;
}}
headerbar .title, headerbar label {{
    color: #ffffff;
    font-weight: bold;
    text-shadow: 1px 1px #0a1883;
}}
button {{
    background-color: #f4f3ee;
    background-image: {BUTTON};
    border: 1px solid #003c74;
    border-radius: 3px;
    color: #000000;
}}
button:hover {{
    box-shadow: inset 0px 0px 0px 2px #f8b330;
}}
button:active, button:checked {{
    background-image: {BUTTON_DOWN};
}}
button.flat:not(:hover):not(:checked), headerbar button, headerbar button:hover, headerbar button:active {{
    background: none;
    border-color: transparent;
    box-shadow: none;
}}
headerbar button {{
    color: #ffffff;
}}
headerbar button:hover {{
    background-color: rgba(255, 255, 255, 0.2);
}}
windowcontrols button {{
    background-image: linear-gradient(to bottom, #5c9cff 0%, #2765e6 60%, #1c4fd2 100%);
    border: 1px solid #ffffff;
    border-radius: 3px;
    color: #ffffff;
}}
windowcontrols button.close {{
    background-image: linear-gradient(to bottom, #f19a7a 0%, #e0532c 45%, #c4391a 100%);
}}
button.suggested-action {{
    background-image: linear-gradient(to bottom, #ffffff 0%, #e6eefc 60%, #c7d7f6 100%);
    border-color: #003c74;
    color: #000000;
    box-shadow: inset 0px 0px 0px 1px #316ac5;
}}
entry, spinbutton, textview {{
    border: 1px solid #7f9db9;
    border-radius: 0px;
}}
"""


def hypr_config(o: dict) -> dict | None:
    """Hyprland options the look sets over yours (None without one)."""
    if active(o) == look_mac.KEY:
        return look_mac.hypr_config()
    if active(o) == look_game.KEY:
        return look_game.hypr_config()
    if active(o) == look_scifi.KEY:
        return look_scifi.hypr_config()
    if active(o) != "luna":
        return None
    return {
        "general": {"border_size": 3, "gaps_in": 3, "gaps_out": 6,
                    "col": {"active_border": "rgb(" + LUNA_BORDER[1:] + ")",
                            "inactive_border": "rgb(" + LUNA_BORDER_INACTIVE[1:] + ")"}},
        "decoration": {"rounding": 8, "rounding_power": 2, "dim_inactive": False, "inactive_opacity": 1.0,
                       "blur": {"enabled": False},
                       "shadow": {"enabled": True, "range": 10, "render_power": 3, "color": "rgba(00000066)",
                                  "color_inactive": "rgba(00000033)"}},
    }


LAUNCHER = "~/.config/hypr/launcher/launcher.sh"
START_STATE = "~/.config/hypr/theme-overrides/luna/start-state.sh"
START_SIGNAL = 12  # SIGRTMIN+12 tells the bar the start menu opened or closed (launcher/startmenu.py)


def bar(o: dict, logo: str = "") -> dict | None:
    """The look's bar, laid over your Bar layout and the tracked config (None without one). Module definitions are
    laid over the config's own (a look's clock format keeps your clock's popup). "extra_bars" are more bars, such as
    Mac style's dock."""
    if active(o) == look_mac.KEY:
        return look_mac.bar(logo)
    if active(o) != "luna":
        return None
    return {
        "position": "bottom", "height": 32, "spacing": 0,
        "modules-left": ["group/startbutton", "wlr/taskbar"],
        # waybar 0.16 gives a custom module no hover state; a group around it has one (#startbutton:hover)
        "group/startbutton": {"orientation": "horizontal", "modules": ["custom/start"]},
        "modules-center": [],
        "modules-right": ["custom/updates", "tray", "pulseaudio", "battery", "custom/recording", "custom/noti", "clock"],
        # pressed in while the start menu is open: the menu signals the bar (RTMIN+12) and start-state.sh says which
        "custom/start": {"exec": f"{START_STATE} '{logo}'" if logo else START_STATE, "return-type": "json",
                         "interval": "once", "signal": START_SIGNAL, "format": "{}", "on-click": LAUNCHER},
        "wlr/taskbar": {"format": "{icon} {title:.24}", "icon-size": 16, "on-click": "activate",
                        "on-click-middle": "close", "tooltip-format": "{title}", "markup": False},
        "tray": {"icon-size": 16, "spacing": 6},
    }


# ---- switching --------------------------------------------------------------------------------------------------------
def state_path() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "hyprdots" / "theme-override.json"


def _read_state() -> dict:
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(data: dict) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def current_wallpaper() -> Path | None:
    link = Path.home() / ".config/rofi/.current_wallpaper"
    try:
        target = link.resolve(strict=True)
    except OSError:
        return None
    return target if target.is_file() else None


def wallpaper_plan(old: str, new: str, now: Path | None, state: dict, chosen: str = "") -> tuple[Path | None, dict]:
    """(wallpaper to set or None, new state) for a switch from old to new. Pure, so it can be tested.

    Going from None to a look remembers the wallpaper you had. Going back puts it back, but only while the look's own
    wallpaper is still showing: one you picked yourself in the meantime is kept. Going from one look to another keeps
    the first remembered wallpaper."""
    state = dict(state)
    if new != NONE:
        if old == NONE and now is not None and "wallpaper" not in state:
            state["wallpaper"] = str(now)
        return wallpaper(new, chosen), state
    saved = state.pop("wallpaper", None)
    look_wallpapers = {str(p) for k, *_ in LOOKS for p in (wallpaper(k), wallpaper(k, chosen)) if p}
    if saved and Path(saved).is_file() and (now is None or str(now) in look_wallpapers):
        return Path(saved), state
    return None, state


def set_wallpaper(path: Path) -> None:
    """Shows path and has the desktop follow it (wallust.sh: colours, then the Theme page parts), in the background,
    as the wallpaper picker does."""
    script = Path.home() / ".config/hypr/scripts/wallust.sh"
    cmd = f'awww img "$1" --transition-type grow --transition-duration 1; exec bash "{script}" "$1"'
    try:
        subprocess.Popen(["sh", "-c", cmd, "sh", str(path)], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def restart_bar() -> None:
    script = Path.home() / ".config/hypr/scripts/restart.sh"
    try:
        subprocess.Popen([str(script), "waybar"], start_new_session=True, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except OSError:
        pass


def reload_hyprland() -> None:
    try:
        subprocess.run(["hyprctl", "reload"], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass


def gtk_before() -> dict | None:
    """What GTK used before the override (font, icons, cursor...), while one is on. Your App settings that you never
    changed default to what GTK uses now (Store.default), which during an override is the look's: they read this
    instead, so switching back gives you your own font again rather than the look's."""
    saved = _read_state().get("gtk")
    return saved if isinstance(saved, dict) else None


def before_switch(store, old: str, new: str) -> None:
    """Call before an override's settings are written: from None to a look, remembers what GTK uses now. Either way
    the store reads its GTK values now, while the old setting still stands, so the refresh after the switch applies
    yours (Store._gtk_now only uses the remembered ones while an override is on)."""
    store._gtk_now()
    if old == NONE and new != NONE and gtk_before() is None:
        state = _read_state()
        state["gtk"] = dict(store._gtk_now())
        try:
            _write_state(state)
        except OSError:
            pass


def animations(o: dict) -> tuple[dict, list[dict]]:
    """Hyprland curves and animations the look sets over window.lua's ({}, [] without any)."""
    if active(o) == look_scifi.KEY:
        return dict(look_scifi.CURVES), list(look_scifi.ANIMATIONS)
    return {}, []


def layer_rules(o: dict) -> list[dict]:
    """Hyprland layer rules the look adds (blur behind see-through panels)."""
    return list(look_mac.LAYER_RULES) if active(o) == look_mac.KEY else []


def button_layout_plan(new: str, now: str | None, state: dict) -> tuple[str | None, dict]:
    """(button layout to set or None, new state). A look with its own layout remembers yours the first time; a look
    without one, or None, puts yours back. Pure, so it can be tested."""
    state = dict(state)
    want = BUTTON_LAYOUTS.get(new)
    if want:
        if "button_layout" not in state and now is not None:
            state["button_layout"] = now
        return (want if want != now else None), state
    saved = state.pop("button_layout", None)
    return (saved if saved is not None and saved != now else None), state


WM_SCHEMA = "org.gnome.desktop.wm.preferences"


def _gsettings(*args: str) -> str | None:
    try:
        r = subprocess.run(["gsettings", *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip().strip("'") if r.returncode == 0 else None


def after_switch(old: str, new: str, chosen: str = "") -> None:
    """What a switch needs beyond the Theme page parts (design.refresh_all writes those): the bar (its modules and
    position may change), Hyprland (theme.lua), and the wallpaper. Back on None, your GTK values have just been
    applied again, so the copy from before_switch is let go."""
    from . import barlayout
    try:
        barlayout.generate()
    except (OSError, ValueError):
        pass
    restart_bar()
    reload_hyprland()
    restart_idle_thunar()
    picture, state = wallpaper_plan(old, new, current_wallpaper(), _read_state(), chosen)
    if new == NONE:
        state.pop("gtk", None)
    layout, state = button_layout_plan(new, _gsettings("get", WM_SCHEMA, "button-layout"), state)
    if layout is not None:
        _gsettings("set", WM_SCHEMA, "button-layout", layout)
    try:
        _write_state(state)
    except OSError:
        pass
    if picture:
        set_wallpaper(picture)


def thunar_idle(clients: list[dict]) -> bool:
    """True when Thunar has no window open: its background copy can be restarted without closing anything of yours."""
    return not any(str(c.get("class", "")).lower() in ("thunar", "org.xfce.thunar") for c in clients)


def restart_idle_thunar() -> None:
    """Thunar runs in the background (thunar --daemon) and keeps the style it started with, so the next folder you open
    would still have the old look. Restarted only while it has no window open; with one open, it follows when it is
    next started."""
    if not shutil.which("thunar"):
        return
    try:
        if subprocess.run(["pgrep", "-x", "thunar"], capture_output=True, timeout=5).returncode:
            return  # not running: it starts with the new look anyway
        out = subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True, timeout=5).stdout
        if not thunar_idle(json.loads(out or "[]")):
            return
        subprocess.run(["thunar", "-q"], capture_output=True, timeout=10)
        cmd = ["thunar", "--daemon"]
        if shutil.which("systemd-run"):  # a scope of its own, not part of the settings window
            cmd = ["systemd-run", "--user", "--scope", "--collect", "--quiet", "--", *cmd]
        subprocess.Popen(cmd, start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass


def chosen_wallpaper(store, key: str) -> str:
    """Your own picture for a look ("" for its built-in one, and for None)."""
    from .schema import BY_ID
    setting = BY_ID.get(f"theme.override_wallpaper_{key}")
    return str(store.get(setting)[0]) if setting else ""


def choose_wallpaper(store, key: str, path: str) -> None:
    """Saves your own picture for a look ("" for its built-in one), and shows it now if that look is on."""
    from . import tomledit
    from .schema import BY_ID
    name = f"override_wallpaper_{key}"
    if f"theme.{name}" not in BY_ID:
        raise ValueError(f"unknown theme override {key!r}")
    if str(path).strip():
        tomledit.set_value(store.local_path, "theme", name, str(path))
    else:
        tomledit.unset(store.local_path, "theme", name)
    store.local = store._safe_read(store.local_path)
    store.staged.pop(f"theme.{name}", None)
    picture = wallpaper(key, path)
    if store.get(BY_ID["theme.override"])[0] == key and picture:
        set_wallpaper(picture)


def switch(store, key: str) -> list[str]:
    """Turns a look on (or None for your own settings) straight away, without touching anything else you have not
    saved. Returns what could not be applied."""
    from . import design, tomledit
    from .schema import BY_ID
    if key not in dict(CHOICES):
        raise ValueError(f"unknown theme override {key!r}")
    old = store.get(BY_ID["theme.override"])[0]
    before_switch(store, old, key)
    if key == NONE:
        tomledit.unset(store.local_path, "theme", "override")
    else:
        tomledit.set_value(store.local_path, "theme", "override", key)
    store.local = store._safe_read(store.local_path)
    store.staged.pop("theme.override", None)
    problems = design.refresh_all(store)
    if old != key:
        after_switch(old, key, chosen_wallpaper(store, key if key != NONE else old))
    return problems
