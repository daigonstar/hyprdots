"""The desktop beyond the bar, built from the Theme page roles (design.py). Each writer uses real colours from the
current wallpaper's palette, so design.refresh_all() runs them again after wallust on every wallpaper change.

- notifications: swaync/theme.css, imported last by swaync/style.css (theme.default.css is the fallback; launch.sh)
- quick tray: hypr/tray/theme.css, which the tray watches (it has built-in colours until then)
- rofi: a marked block appended to wallust's ~/.config/rofi/colors.rasi, which every rofi theme imports
- window borders: hypr/theme.lua, read by window.lua when it exists
- lock screen: hyprlock.local.conf, when you have one (the password line takes the accent)
- Qt apps: follow GTK through QT_QPA_PLATFORMTHEME (environment.lua); KDE ones also read the [Colors:*] groups of
  ~/.config/kdeglobals
- apps: a marked block in ~/.config/gtk-3.0/gtk.css and gtk-4.0/gtk.css with GTK's named colours, the adw-gtk3 style
  for GTK 3 apps, and the icons, cursor and font from the Apps group. Flatpak apps are allowed to read those folders."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from . import design, gtktheme, theme

HOME = Path.home()
ROFI_MARK = "/* hyprdots theme"
GTK_MARK, GTK_END = "/* hyprdots theme: ", "/* hyprdots theme end */"
FLATPAK_GTK = ("xdg-config/gtk-3.0:ro", "xdg-config/gtk-4.0:ro")
ADW_GTK3 = "adw-gtk3"  # the adw-gtk-theme package: GTK 3 apps drawn like libadwaita, following its named colours


def swaync_css(o: dict) -> str:
    c = design.resolved(o)
    o = {**design.DEFAULTS, **o}
    base_a = int(o["base_opacity"]) / 100
    tint = design.alpha_rgba(c["surface"], 0.22)
    return f"""/* Notification colours and font, made by hypr-settings from the Theme page (rewritten when the wallpaper changes).
   Imported last by style.css, so these win over the theme's own colour names. Do not edit by hand. */
@define-color text {c['base_text']};
@define-color background {c['base']};
@define-color background-alt {tint};
@define-color selected {c['accent']};
@define-color button-active {c['accent']};
@define-color hover {design.alpha_rgba(c['secondary'], 0.35)};
@define-color hovered {c['secondary']};
@define-color urgent {c['attention']};
@define-color swaync-bg {design.alpha_rgba(c['base'], base_a)};
@define-color swaync-bg-soft {design.alpha_rgba(c['base'], max(0.0, base_a - 0.04))};

* {{
    font-family: {design.font_list(o)};
}}
"""


def write_swaync(o: dict) -> None:
    design.write(HOME / ".config/swaync/theme.css", swaync_css(o))
    subprocess.run(["swaync-client", "--reload-css"], capture_output=True, timeout=10)


def tray_css(o: dict) -> str:
    c = design.resolved(o)
    o = {**design.DEFAULTS, **o}
    return f"""/* Quick tray colours and font, made by hypr-settings from the Theme page (rewritten when the wallpaper changes).
   Do not edit by hand. */
@define-color tray_bg {design.alpha_rgba(c['base'], int(o['base_opacity']) / 100)};
@define-color tray_text {c['base_text']};
@define-color tray_card {design.alpha_rgba(c['surface'], 0.22)};
@define-color tray_accent {c['accent']};
@define-color tray_on_accent {c['base']};
@define-color tray_muted {design.alpha_rgba(c['base_text'], 0.65)};
@define-color tray_attention {c['attention']};

* {{
    font-family: {design.font_list(o)};
}}
"""


def write_tray(o: dict) -> None:
    design.write(HOME / ".config/hypr/tray/theme.css", tray_css(o))


def rofi_block(o: dict) -> str:
    c = design.resolved(o)
    o = {**design.DEFAULTS, **o}
    base = design.alpha_rgba(c["base"], int(o["base_opacity"]) / 100)
    pairs = {
        "background": base, "background-color": "transparent", "background-alt": c["surface"],
        "foreground": c["base_text"], "border-color": c["accent"], "selected": c["accent"],
        "normal-background": base, "normal-foreground": c["base_text"],
        "alternate-normal-background": base, "alternate-normal-foreground": c["base_text"],
        "active-background": c["surface"], "active-foreground": c["text"],
        "alternate-active-background": c["surface"], "alternate-active-foreground": c["text"],
        "urgent-background": c["attention"], "urgent-foreground": c["base"],
        "alternate-urgent-background": c["attention"], "alternate-urgent-foreground": c["base"],
        "selected-normal-background": c["accent"], "selected-normal-foreground": c["base"],
        "selected-active-background": c["accent"], "selected-active-foreground": c["base"],
        "selected-urgent-background": c["attention"], "selected-urgent-foreground": c["base"],
        "font": f'"{design.font_pango(o)} 13"',
    }
    body = "".join(f"    {k}: {v};\n" for k, v in pairs.items())
    return f"\n{ROFI_MARK}: roles from the settings Theme page, rewritten when the wallpaper changes */\n* {{\n{body}}}\n"


def write_rofi(o: dict) -> None:
    path = HOME / ".config/rofi/colors.rasi"
    text = path.read_text(encoding="utf-8")
    if ROFI_MARK in text:  # replace the previous block, keep what wallust wrote
        text = text[:text.index(ROFI_MARK)].rstrip("\n") + "\n"
    design.write(path, text + rofi_block(o))


def hypr_lua(o: dict) -> str:
    c = design.resolved(o)
    lua = lambda h: f'"rgb({h[1:]})"'  # noqa: E731
    return ("-- Window border colours, made by hypr-settings from the Theme page (rewritten when the wallpaper changes).\n"
            "-- window.lua uses these when this file exists. Do not edit by hand.\n"
            "return {\n"
            f"    active_border = {lua(c['accent'])},\n"
            f"    inactive_border = {lua(c['muted'])},\n"
            f"    group_active = {lua(c['accent'])},\n"
            f"    group_inactive = {lua(c['muted'])},\n"
            "}\n")


def write_hypr(o: dict) -> None:
    design.write(HOME / ".config/hypr/theme.lua", hypr_lua(o))


def write_lock(store) -> None:
    """Only rewrites the lock screen when you have saved your own look or chosen a picture (else the shipped one stays as it is)."""
    from . import account, lockscreen
    path = lockscreen.local_path(store.dir)
    if path.exists() or account.picture_path().exists():
        lockscreen.write(path, lockscreen.render(store.lock_options(), accent=design.resolved(design.theme_options(store))["accent"]))


def gtk_colours(o: dict) -> dict[str, str]:
    """GTK's named colours (libadwaita's, which adw-gtk3 follows too) from the large panel colours and the accent, the
    same ones and the same steps as the settings window (gui/ui.css), which this file also reaches."""
    c = theme.colors(o)
    bg, fg, accent = c["bg"], c["fg"], c["accent"]
    shade = lambda t: theme.mix(bg, fg, t)  # noqa: E731  (a step from the panel colour towards the text)
    return {"accent_color": accent, "accent_bg_color": accent,
           "accent_fg_color": bg if theme.luminance(accent) > 0.3 else "#ffffff",
           "window_bg_color": bg, "window_fg_color": fg, "view_bg_color": bg, "view_fg_color": fg,
           "headerbar_bg_color": bg, "headerbar_fg_color": fg, "headerbar_backdrop_color": bg,
           "sidebar_bg_color": shade(0.03), "sidebar_fg_color": fg, "sidebar_backdrop_color": shade(0.02),
           "secondary_sidebar_bg_color": shade(0.02), "secondary_sidebar_fg_color": fg,
           "card_bg_color": shade(0.05), "card_fg_color": fg, "dialog_bg_color": shade(0.04), "dialog_fg_color": fg,
           "popover_bg_color": shade(0.06), "popover_fg_color": fg, "thumbnail_bg_color": shade(0.06), "thumbnail_fg_color": fg,
           # the older names: plain GTK 4 apps (no libadwaita) and most GTK 3 themes draw with these
           "theme_bg_color": bg, "theme_fg_color": fg, "theme_base_color": shade(0.02), "theme_text_color": fg,
           "theme_selected_bg_color": accent, "theme_selected_fg_color": bg if theme.luminance(accent) > 0.3 else "#ffffff",
           "theme_unfocused_bg_color": bg, "theme_unfocused_fg_color": fg, "theme_unfocused_base_color": shade(0.02),
           "theme_unfocused_text_color": fg, "theme_unfocused_selected_bg_color": accent,
           "theme_unfocused_selected_fg_color": bg if theme.luminance(accent) > 0.3 else "#ffffff",
           "borders": shade(0.12), "unfocused_borders": shade(0.10)}


def gtk_css(o: dict, version: str) -> str:
    """The marked block for gtk-<version>/gtk.css. GTK 4 apps read libadwaita's CSS variables; @define-color covers
    GTK 3 and older libadwaita."""
    colours = gtk_colours(o)
    text = GTK_MARK + "colours from the settings Theme page, rewritten when the wallpaper changes. Your own CSS can go\n" \
        "   above or below this block. */\n"
    text += "".join(f"@define-color {k} {v};\n" for k, v in colours.items())
    if version == "4.0":
        text += ":root {\n" + "".join(f"    --{k.replace('_', '-')}: {v};\n" for k, v in colours.items()
                                       if not k.startswith(("theme_", "borders", "unfocused_"))) + "}\n"
    return text + GTK_END + "\n"


def _set_block(path: Path, block: str | None) -> None:
    """Puts the block in path (replacing the previous one, keeping anything else), or takes it out (None). A file left
    empty is removed. A link to an installed theme's gtk.css (set when apps were not coloured) is replaced."""
    if path.is_symlink() and "/themes/" in str(path.readlink()):
        path.unlink()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    if GTK_MARK in text:
        start = text.index(GTK_MARK)
        end = text.find(GTK_END, start)
        end = len(text) if end < 0 else end + len(GTK_END)
        text = text[:start].rstrip("\n") + ("\n" if text[:start].strip() else "") + text[end:].lstrip("\n")
    if block:
        text = text.rstrip("\n") + ("\n\n" if text.strip() else "") + block
    if text.strip():
        path.parent.mkdir(parents=True, exist_ok=True)
        design.write(path, text)
    elif path.exists():
        path.unlink()


def write_gtk(o: dict) -> None:
    """Applies the Apps group: colours (or your GTK theme), dark or light, icons, cursor and font. Only what changed is
    applied, since this runs on every wallpaper change and setting the cursor or theme again makes apps redraw."""
    o = {**design.DEFAULTS, **o}
    coloured = bool(o["gtk_colours"])
    dark = theme.luminance(theme.colors(o)["bg"]) < 0.4
    if coloured and gtktheme.theme_dir(ADW_GTK3):
        style = ADW_GTK3 + ("-dark" if dark else "")
    else:
        style = str(o["gtk_theme"])
    if coloured:
        gtktheme.link_gtk4_theme(None)  # links to an installed theme would hide the colours from GTK 4 apps
        flatpak_can_read_gtk()
    for version in ("3.0", "4.0"):
        _set_block(gtktheme.config_home() / f"gtk-{version}" / "gtk.css", gtk_css(o, version) if coloured else None)
    if not coloured:
        gtktheme.link_gtk4_theme(style)
    want = {"theme": style, "icons": str(o["icons"]), "cursor": str(o["cursor"]), "cursor_size": str(int(o["cursor_size"])),
            "font": f"{o['app_font']} {int(o['app_font_size'])}", "dark": dark}
    now = gtktheme.current()
    changes = {k: v for k, v in want.items() if (now[k] if k == "dark" else str(now[k])) != v}
    if changes:
        ok, message = gtktheme.apply(link_gtk4=False, **changes)
        if not ok:
            raise OSError(message)


def kde_colours(o: dict) -> str:
    """The [Colors:*] groups KDE apps draw with, in the same steps as gtk_colours, so they match Qt and GTK apps."""
    g = gtk_colours(o)
    triple = lambda colour: ",".join(str(round(v * 255)) for v in design.rgb(colour))  # noqa: E731
    fg, accent, on_accent = g["window_fg_color"], g["accent_color"], g["accent_fg_color"]
    muted = theme.mix(g["window_bg_color"], fg, 0.65)
    alert = design.resolved(o)["attention"]

    def group(name, background, alternate, text=fg, inactive=muted):
        keys = {"BackgroundNormal": background, "BackgroundAlternate": alternate, "ForegroundNormal": text,
                "ForegroundInactive": inactive, "ForegroundActive": accent, "ForegroundLink": accent,
                "ForegroundVisited": accent, "ForegroundNegative": alert, "ForegroundNeutral": alert,
                "ForegroundPositive": accent, "DecorationFocus": accent, "DecorationHover": accent}
        return f"[Colors:{name}]\n" + "".join(f"{k}={triple(v)}\n" for k, v in keys.items()) + "\n"
    base, shaded, card = g["window_bg_color"], g["theme_base_color"], g["card_bg_color"]
    button = theme.mix(base, fg, 0.14)  # on a black wallpaper palette, anything fainter hides the button
    return (group("Window", base, shaded) + group("View", shaded, card) + group("Button", button, card)
            + group("Header", base, shaded) + group("Tooltip", g["popover_bg_color"], base)
            + group("Complementary", base, shaded) + group("Selection", accent, accent, on_accent, on_accent))


def with_kde_colours(text: str, colours: str | None) -> str:
    """kdeglobals with its colour groups replaced (or removed, on None). KDE apps keep other settings there."""
    kept, skipping = [], False
    for line in text.splitlines(keepends=True):
        if line.startswith("["):
            skipping = line.startswith("[Colors:")
        if not skipping:
            kept.append(line)
    rest = "".join(kept).strip()
    return (rest + "\n\n" if rest else "") + (colours or "")


def write_qt(o: dict) -> None:
    o = {**design.DEFAULTS, **o}
    path = HOME / ".config/kdeglobals"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    new = with_kde_colours(text, kde_colours(o) if o["gtk_colours"] else None)
    if new != text:
        design.write(path, new)


def flatpak_can_read_gtk() -> None:
    """Flatpak apps only see ~/.config/gtk-3.0 and gtk-4.0 (the colours) when allowed. Allowed once, for every app,
    read-only. GTK 3 Flatpak apps also need the theme as a Flatpak (the installer adds org.gtk.Gtk3theme.adw-gtk3)."""
    if not shutil.which("flatpak"):
        return
    try:
        shown = subprocess.run(["flatpak", "override", "--user", "--show"], capture_output=True, text=True, timeout=20).stdout
        missing = [f for f in FLATPAK_GTK if f not in shown]
        if missing:
            subprocess.run(["flatpak", "override", "--user", *(f"--filesystem={f}" for f in missing)],
                           capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        pass
