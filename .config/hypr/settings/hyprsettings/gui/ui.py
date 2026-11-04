"""Small building blocks shared by the pages: dialogs, tags, page layout and the wallust style sheet."""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import theme  # noqa: E402

PAGE_GLYPHS = {
    "User": "\U000f0004", "Assistant": "\U000f0674", "Assistant Monitor": "\U000f04c5", "Calendar": "\U000f00ed", "Network": "\U000f05a9", "Cloud drives": "\U000f015f",
    "Displays": "\U000f0379", "Workspaces": "\U000f0570", "Window rules": "\U000f05b5", "Power & lock": "\U000f0904", "Theme": "\U000f08b5", "Bar layout": "\U000f0e09", "Launcher": "\U000f0349", "Hyprland": "", "Keybinds": "\U000f030c",
    "File types": "\U000f0214", "Hyprdots": None,  # Hyprdots uses the Super key logo
}


def css() -> str:
    c = theme.colors()
    return f"""
:root {{
    --accent-bg-color: {c['accent']};
    --accent-fg-color: {c['bg']};
    --accent-color: {c['accent']};
    --window-bg-color: {c['bg']};
    --window-fg-color: {c['fg']};
    --view-bg-color: {c['bg']};
    --view-fg-color: {c['fg']};
    --headerbar-bg-color: {c['bg']};
    --headerbar-fg-color: {c['fg']};
    --sidebar-bg-color: {theme.mix(c['bg'], c['fg'], 0.03)};
    --sidebar-fg-color: {c['fg']};
    --card-bg-color: {theme.mix(c['bg'], c['fg'], 0.05)};
    --card-fg-color: {c['fg']};
    --dialog-bg-color: {theme.mix(c['bg'], c['fg'], 0.04)};
    --dialog-fg-color: {c['fg']};
    --popover-bg-color: {theme.mix(c['bg'], c['fg'], 0.06)};
    --popover-fg-color: {c['fg']};
}}
.glyph {{ font-family: "{theme.ICON_FONT}"; font-size: 17px; color: {c['accent']}; min-width: 26px; }}
.sidebar-title {{ font-family: "{theme.ICON_FONT}"; font-size: 15px; font-weight: 800; }}
.sidebar-title .glyph {{ font-size: 22px; }}
.intro {{ color: alpha({c['fg']}, 0.7); margin: 6px 4px 4px 4px; }}
.tag {{ font-size: 11px; font-weight: 700; border-radius: 99px; padding: 1px 8px; }}
.tag.changed {{ background: alpha(#e8b84a, 0.18); color: #e8b84a; }}
.tag.yours {{ background: alpha({c['accent']}, 0.16); color: {c['accent']}; }}
.tag.default {{ background: alpha({c['fg']}, 0.08); color: alpha({c['fg']}, 0.6); }}
.tag.bad {{ background: alpha(#ff6b6b, 0.16); color: #ff6b6b; }}
.savebar {{ background: {theme.mix(c['bg'], '#e8b84a', 0.12)}; border-top: 1px solid alpha(#e8b84a, 0.35); padding: 10px 16px; }}
.savebar label {{ font-weight: 700; }}
.error-text {{ color: #ff6b6b; }}
entry.mono, .mono {{ font-family: monospace; }}
.cap {{
    font-family: "{theme.ICON_FONT}"; font-weight: 700; font-size: 12px;
    background: alpha({c['fg']}, 0.09); border: 1px solid alpha({c['fg']}, 0.16); border-bottom-width: 3px;
    border-radius: 7px; padding: 1px 8px; min-width: 14px;
}}
.cap.super {{ color: {c['bg']}; background: {c['accent']}; border-color: shade({c['accent']}, 0.7); font-size: 15px; padding: 0 8px; }}
.plus {{ color: alpha({c['fg']}, 0.35); font-size: 11px; }}
"""


def tag(source: str) -> Gtk.Label:
    """Little pill after a row: 'unsaved' for staged edits, 'custom' for your saved value, nothing for defaults."""
    text = {"changed": "unsaved", "yours": "custom"}.get(source, "")
    label = Gtk.Label(label=text, css_classes=["tag", source], valign=Gtk.Align.CENTER, visible=bool(text))
    return label


def set_tag(label: Gtk.Label, source: str) -> None:
    for c in ("changed", "yours"):
        label.remove_css_class(c)
    text = {"changed": "unsaved", "yours": "custom"}.get(source, "")
    if text:
        label.add_css_class(source)
    label.set_label(text)
    label.set_visible(bool(text))


def page_box(intro: str) -> tuple[Gtk.ScrolledWindow, Gtk.Box]:
    """A scrolling page with a centred column; returns (scroller, column to append groups to)."""
    column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24, margin_top=18, margin_bottom=30, margin_start=14, margin_end=14)
    if intro:
        column.append(Gtk.Label(label=intro, wrap=True, xalign=0, css_classes=["intro"]))
    clamp = Adw.Clamp(maximum_size=820, tightening_threshold=600, child=column)
    scroller = Gtk.ScrolledWindow(child=clamp, hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
    return scroller, column


def key_caps(keys: str, logo: str) -> Gtk.Box:
    """'SUPER + SHIFT + T' drawn as key caps, Super as the chosen logo."""
    names = {"control": "Ctrl", "ctrl": "Ctrl", "shift": "Shift", "alt": "Alt", "space": "Space", "return": "Enter",
             "escape": "Esc", "tab": "Tab", "left": "←", "right": "→", "up": "↑", "down": "↓",
             "mouse_down": "Scroll ↓", "mouse_up": "Scroll ↑"}
    box = Gtk.Box(spacing=4, valign=Gtk.Align.CENTER)
    if keys == "none":
        box.append(Gtk.Label(label="unbound", css_classes=["dim-label"]))
        return box
    for i, part in enumerate(p.strip() for p in keys.split("+") if p.strip()):
        if i:
            box.append(Gtk.Label(label="+", css_classes=["plus"]))
        if part.upper() in ("SUPER", "MOD4", "WIN"):
            box.append(Gtk.Label(label=theme.super_glyph(logo), css_classes=["cap", "super"]))
        else:
            box.append(Gtk.Label(label=names.get(part.lower(), part.upper() if len(part) == 1 else part), css_classes=["cap"]))
    return box


# ---- dialogs ----------------------------------------------------------------------------------------------------
def message(parent: Gtk.Widget, title: str, body: str) -> None:
    d = Adw.AlertDialog(heading=title, body=body)
    d.add_response("ok", "OK")
    d.present(parent)


def confirm(parent: Gtk.Widget, title: str, body: str, yes: str, on_yes: Callable[[], None],
            destructive: bool = False, no: str = "Cancel", on_no: Callable[[], None] | None = None) -> None:
    d = Adw.AlertDialog(heading=title, body=body)
    d.add_response("no", no)
    d.add_response("yes", yes)
    d.set_response_appearance("yes", Adw.ResponseAppearance.DESTRUCTIVE if destructive else Adw.ResponseAppearance.SUGGESTED)
    d.set_default_response("yes")
    d.set_close_response("no")
    d.connect("response", lambda _d, r: on_yes() if r == "yes" else (on_no and on_no()))
    d.present(parent)


def ask(parent: Gtk.Widget, title: str, on_submit: Callable[..., None], fields: list[tuple[str, str]] | None = None,
        body: str = "", ok: str = "OK", secret: bool = False, error: str = "") -> None:
    """Asks for one or more lines of text: fields are (label, text) or (label, text, hidden). on_submit(*values) may
    raise ValueError: the dialog then comes back with the message, keeping what was typed."""
    fields = fields or [("", "")]
    d = Adw.AlertDialog(heading=title, body=body)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    entries = []
    for label, text, *hidden in fields:
        if label:
            box.append(Gtk.Label(label=label, xalign=0, css_classes=["caption-heading"]))
        hide = hidden[0] if hidden else secret
        entry = Gtk.PasswordEntry(show_peek_icon=True) if hide else Gtk.Entry(text=text)
        if hide and text:
            entry.set_text(text)
        entry.connect("activate", lambda _e: d.response("ok"))
        box.append(entry)
        entries.append(entry)
    if error:
        box.append(Gtk.Label(label=error, wrap=True, xalign=0, css_classes=["error-text"]))
    d.set_extra_child(box)
    d.add_response("cancel", "Cancel")
    d.add_response("ok", ok)
    d.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
    d.set_default_response("ok")
    d.set_close_response("cancel")

    def answered(_d, response):
        if response != "ok":
            return
        values = [e.get_text() for e in entries]
        try:
            on_submit(*values)
        except ValueError as e:
            ask(parent, title, on_submit, [(f[0], v, *f[2:]) for f, v in zip(fields, values)], body, ok, secret, str(e))
    d.connect("response", answered)
    d.present(parent)
    entries[0].grab_focus()
