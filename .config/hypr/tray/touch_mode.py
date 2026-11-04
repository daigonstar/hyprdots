"""Touch mode: everything sized for fingers while no keyboard is attached, and back to normal with one. tablet_mode.py decides
and calls apply(); each part of the desktop then has what it needs in a file it already reads:
- the state file: the bar's badge and the quick tray look here
- the bar: restarted when this changes, for launch.sh to pick waybar/config-touch, at the bottom, and tablet.css for its sizes
- rofi/touch.rasi: imported by rofi's themes, read each time a picker opens
- gtk-3.0 and gtk-4.0/gtk.css: a marked block for GTK apps, read when each app starts. Anything else in those files is left alone
Apps that are not GTK (browsers, Electron and Qt apps) size themselves."""
import re
import subprocess
from pathlib import Path

STATE = Path.home() / ".local/state/hyprdots/touch-mode"
BAR_STYLE = Path.home() / ".config/waybar/tablet.css"
ROFI_STYLE = Path.home() / ".config/rofi/touch.rasi"
GTK_FILES = [Path.home() / f".config/gtk-{version}/gtk.css" for version in ("3.0", "4.0")]
GTK_MARK = "/* hyprdots touch mode: written while no keyboard is attached, and taken out again */\n"
GTK_END = "/* hyprdots touch mode end */\n"

BAR_MODULES = ("clock", "custom-assistant", "custom-touchmode", "custom-launcher", "custom-overview", "pulseaudio", "battery", "network", "bluetooth", "idle_inhibitor", "custom-power",
               "custom-noti", "custom-trayarrow", "custom-settingsarrow", "custom-recording", "custom-updates", "cpu", "memory", "temperature",
               "backlight", "mpris", "language", "custom-wallpaper", "custom-drive", "custom-keys", "tray", "window")
BAR_CSS = "/* Written by hypr/tray/touch_mode.py while no keyboard is attached */\n" \
    "window#waybar * { font-size: 22px; }\n" \
    "window#waybar #custom-ws1, window#waybar #custom-ws2, window#waybar #custom-ws3 { min-width: 76px; min-height: 52px; padding: 0; font-size: 26px; }\n" \
    "window#waybar #custom-launcher, window#waybar #custom-overview { min-width: 64px; font-size: 26px; }\n" \
    + ",\n".join(f"window#waybar #{name}" for name in BAR_MODULES) + " { min-height: 44px; padding: 0 16px; }\n"

ROFI_CSS = """/* Written by hypr/tray/touch_mode.py while no keyboard is attached */
configuration {
    me-select-entry: "";
    me-accept-entry: [ MousePrimary, MouseSecondary, MouseDPrimary ];
}
element { padding: 16px; }
element-text { font: "sans 16"; }
inputbar { padding: 14px; }
"""

GTK_CSS = """button, combobox button, menubutton > button, dropdown > button { min-height: 40px; min-width: 40px; padding: 6px 14px; }
entry, spinbutton, searchbar entry { min-height: 44px; }
row, list row, listview > row, columnview > listview > row, modelbutton { min-height: 48px; }
check, radio { min-width: 28px; min-height: 28px; }
switch { min-width: 60px; min-height: 34px; }
switch slider, switch > slider { min-width: 30px; min-height: 30px; }
scale slider { min-width: 28px; min-height: 28px; }
scale trough { min-height: 8px; }
scrollbar slider { min-width: 12px; min-height: 12px; }
"""

# The quick tray's own sizes: it is running already, so it loads these itself
TRAY_CSS = """
.tile-main { min-height: 68px; }
scale slider { min-width: 32px; min-height: 32px; }
scale trough { min-height: 10px; }
"""


def active() -> bool:
    return STATE.exists()


def write_if_changed(path: Path, text: str) -> None:
    try:
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    except OSError:
        pass


def with_block(text: str, wanted: bool) -> str:
    """text with the marked block in or out, and everything else as it was."""
    pattern = re.escape(GTK_MARK) + r".*?" + re.escape(GTK_END)
    text = re.sub(r"\n*" + pattern, "\n", text, flags=re.S) if GTK_MARK in text else text
    text = text.rstrip("\n") + "\n" if text.strip() else ""
    return text + ("\n" if text else "") + GTK_MARK + GTK_CSS + GTK_END if wanted else text


def apply(wanted: bool) -> None:
    changed = wanted != active()
    write_if_changed(BAR_STYLE, BAR_CSS if wanted else "")
    write_if_changed(ROFI_STYLE, ROFI_CSS if wanted else "")
    for path in GTK_FILES:
        try:
            write_if_changed(path, with_block(path.read_text(encoding="utf-8") if path.exists() else "", wanted))
        except OSError:
            pass
    if wanted:
        write_if_changed(STATE, "on\n")
    else:
        STATE.unlink(missing_ok=True)
    if changed:  # the touch bar is another config, and launch.sh picks by the state file
        subprocess.Popen(["systemctl", "--user", "restart", "--no-block", "waybar.service"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
