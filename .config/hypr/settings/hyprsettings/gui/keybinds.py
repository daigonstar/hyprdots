"""Keybinds page: every rebindable action with its combo drawn as key caps. Clicking one opens a dialog that
records the combo you press.

Hyprland keeps combos it already uses for itself, so those never reach this window. The modifier buttons in
the dialog cover that case: switch on Super (or any other) and press only the key."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from .. import theme  # noqa: E402
from ..schema import BY_ID  # noqa: E402
from . import ui  # noqa: E402

MOD_KEYS = {  # keyval names of modifier keys -> the modifier they stand for
    "Super_L": "SUPER", "Super_R": "SUPER", "Meta_L": "SUPER", "Meta_R": "SUPER", "Hyper_L": "SUPER",
    "Control_L": "CTRL", "Control_R": "CTRL", "Alt_L": "ALT", "Alt_R": "ALT", "ISO_Level3_Shift": "ALT",
    "Shift_L": "SHIFT", "Shift_R": "SHIFT",
}
MASKS = (("SUPER", Gdk.ModifierType.SUPER_MASK), ("CTRL", Gdk.ModifierType.CONTROL_MASK),
         ("ALT", Gdk.ModifierType.ALT_MASK), ("SHIFT", Gdk.ModifierType.SHIFT_MASK))
HOW_TO = ("To add a brand new keybind, open keybinds.lua and add one line inside the KEYBINDS-BEGIN / KEYBINDS-END list:\n\n"
          '{ id = "calc", label = "Open calculator", keys = "SUPER + equal", action = hl.dsp.exec_cmd("gnome-calculator") },\n\n'
          "Keep the id unique and put a '-- group: Name' comment above a section to start a new heading. Reload Hyprland "
          "and the new action shows up here, ready to rebind.")


def build(win) -> Gtk.Widget:
    store = win.store
    logo = store.get(BY_ID["look.super_logo"])[0]
    scroller, column = ui.page_box("Click an action to give it a new key combo. Super is the Windows key. Changes apply when "
                                   "Hyprland reloads. How to add a keybind of your own is at the bottom.")
    rows = store.keybind_rows()
    if not rows:
        column.append(Adw.StatusPage(title="No keybinds found", icon_name="input-keyboard-symbolic",
                                     description=f"keybinds.lua needs its KEYBINDS-BEGIN list in {store.dir}."))
        return scroller

    group, last = None, object()
    for b in rows:
        if group is None or b["group"] != last:
            group = Adw.PreferencesGroup(title=b["group"] or "Other")
            column.append(group)
            last = b["group"]
        keys, source = store.get_keybind(b)
        row = Adw.ActionRow(title=b["label"], activatable=True, use_markup=False,
                            tooltip_text=f"Default: {b['keys']}. Click to change.")
        row.add_suffix(ui.tag(source))
        if source != "default":
            undo = Gtk.Button(icon_name="edit-undo-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                              tooltip_text=f"Put the default back ({b['keys']})")
            undo.connect("clicked", lambda _b, b=b: (store.reset_keybind(b), win.refresh()))
            row.add_suffix(undo)
        row.add_suffix(ui.key_caps(keys, logo))
        row.connect("activated", lambda _r, b=b: capture(win, b, logo))
        group.add(row)

    help_group = Adw.PreferencesGroup(title="Your own keybinds")
    how = Adw.ExpanderRow(title="How to add a new keybind", subtitle=str(store.keybinds_path), use_markup=False)
    how.add_row(Adw.ActionRow(title=HOW_TO, use_markup=False, css_classes=["mono"]))
    help_group.add(how)
    column.append(help_group)
    return scroller


def key_name(win: Gtk.Widget, keycode: int, keyval: int) -> str:
    """The key itself, ignoring Shift (Shift+1 is '1', not 'exclam'), in the form keybinds.lua uses."""
    ok, plain, *_ = win.get_display().translate_key(keycode, 0, 0)
    name = Gdk.keyval_name(plain if ok and plain else keyval) or ""
    return name.upper() if len(name) == 1 else name


def capture(win, b: dict, logo: str) -> None:
    store = win.store
    current = store.get_keybind(b)[0]
    mods = {m: False for m, _ in MASKS}
    state = {"key": ""}

    dialog = Adw.Dialog(title=b["label"], content_width=520)
    view = Adw.ToolbarView()
    view.add_top_bar(Adw.HeaderBar())
    body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, margin_top=8, margin_bottom=20, margin_start=24, margin_end=24)
    view.set_content(body)
    dialog.set_child(view)

    body.append(Gtk.Label(label="Press the new key combo", css_classes=["title-3"]))
    preview = Gtk.Box(halign=Gtk.Align.CENTER, height_request=44)
    body.append(preview)
    note = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, css_classes=["dim-label"],
                     label="If Hyprland already uses a combo it never reaches this window. Switch the modifiers on below "
                           "and press just the key.")
    body.append(note)

    toggles = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER, css_classes=["linked"])
    buttons = {}
    for m, _mask in MASKS:
        t = Gtk.ToggleButton(focusable=False)
        inner = Gtk.Box(spacing=6)
        if m == "SUPER" and logo != "text":
            inner.append(Gtk.Label(label=theme.super_glyph(logo), css_classes=["glyph"]))
        inner.append(Gtk.Label(label=m.title()))
        t.set_child(inner)
        t.connect("toggled", lambda t, m=m: (mods.__setitem__(m, t.get_active()), redraw()))
        buttons[m] = t
        toggles.append(t)
    body.append(toggles)
    error = Gtk.Label(wrap=True, css_classes=["error-text"], visible=False)
    body.append(error)

    actions = Gtk.Box(spacing=8, halign=Gtk.Align.END)
    unbind = Gtk.Button(label="Unbind", tooltip_text="Switch this action off")
    default = Gtk.Button(label="Default", tooltip_text=f"Use the default ({b['keys']})")
    use = Gtk.Button(label="Use this combo", css_classes=["suggested-action"], sensitive=False)
    for w in (unbind, default, use):
        actions.append(w)
    body.append(actions)

    def combo() -> str:
        if not state["key"]:
            return ""
        return " + ".join([m for m, _ in MASKS if mods[m]] + [state["key"]])

    def redraw():
        child = preview.get_first_child()
        while child:
            preview.remove(child)
            child = preview.get_first_child()
        text = combo()
        if text:
            preview.append(ui.key_caps(text, logo))
        else:
            held = [m for m, _ in MASKS if mods[m]]
            if held:
                preview.append(ui.key_caps(" + ".join(held), logo))
            else:
                now = Gtk.Box(spacing=10, valign=Gtk.Align.CENTER)
                now.append(Gtk.Label(label="Now", css_classes=["dim-label"]))
                now.append(ui.key_caps(current, logo))
                preview.append(now)
        use.set_sensitive(bool(text))
        error.set_visible(False)

    def pressed(_ctl, keyval, keycode, st):
        name = Gdk.keyval_name(keyval) or ""
        if name in MOD_KEYS:
            buttons[MOD_KEYS[name]].set_active(True)
            return True
        if keyval == Gdk.KEY_Escape and not any(mods.values()):
            dialog.close()
            return True
        for m, mask in MASKS:
            if st & mask:
                buttons[m].set_active(True)
        state["key"] = key_name(win, keycode, keyval)
        redraw()
        return True
    keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
    keys.connect("key-pressed", pressed)
    dialog.add_controller(keys)

    def apply(text):
        try:
            store.stage_keybind(b, text)
        except ValueError as e:
            error.set_label(str(e))
            error.set_visible(True)
            return
        dialog.close()
        win.refresh()
    use.connect("clicked", lambda _b: apply(combo()))
    unbind.connect("clicked", lambda _b: apply("none"))
    default.connect("clicked", lambda _b: (store.reset_keybind(b), dialog.close(), win.refresh()))

    redraw()
    dialog.present(win)
