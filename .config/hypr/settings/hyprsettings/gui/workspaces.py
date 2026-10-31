"""Workspaces page: which screen each of the ten workspaces opens on, which one a screen starts on, a name, whether it
always shows in the bar, and an app to open when it is empty. Edits wait for Save like the other settings; saving
writes workspaces.lua, reloads Hyprland and moves open workspaces onto their screen."""

from __future__ import annotations

import copy

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import displays, workspaces  # noqa: E402
from ..schema import PAGE_INTRO  # noqa: E402
from . import ui  # noqa: E402

KEY = "Workspaces"


class Pending:
    """The page's edits, kept on the window so they survive switching pages until Save or Discard."""

    def __init__(self, path):
        self.path = path
        self.expanded: set[int] = set()
        self.reload()

    def reload(self) -> None:
        self.rules = workspaces.read(self.path)
        self.saved = workspaces.rows(self.rules)
        self.rows = copy.deepcopy(self.saved)

    def count(self) -> int:
        return sum(1 for a, b in zip(self.rows, self.saved) if a != b)

    def save(self) -> tuple[bool, str]:
        rules = workspaces.merge(self.rules, self.rows)
        try:
            workspaces.write(self.path, rules)
        except OSError as e:
            return False, f"Could not save workspaces.lua: {e}"
        ok, msg = workspaces.apply(rules)
        self.reload()
        return ok, ("Workspaces saved. " + msg) if ok else msg

    def discard(self) -> None:
        self.reload()


def build(win) -> Gtk.Widget:
    if KEY not in win.pending:
        win.pending[KEY] = Pending(win.store.dir / "workspaces.lua")
    state: Pending = win.pending[KEY]
    scroller, column = ui.page_box(PAGE_INTRO[KEY])

    screens = sorted((m for m in displays.read() if not m["disabled"]), key=lambda m: (m["x"], m["y"]))
    names = [m["name"] for m in screens]
    known = names + sorted({r["monitor"] for r in state.rows if r["monitor"] and r["monitor"] not in names})

    column.append(quick_group(win, state, names))
    group = Adw.PreferencesGroup(title="Your workspaces", description="Click one to change it.")
    for row in state.rows:
        group.add(workspace_row(win, state, row, known, names))
    column.append(group)
    return scroller


def summary(row: dict, connected: list[str]) -> str:
    where = row["monitor"] or "Any screen"
    if row["monitor"] and row["monitor"] not in connected:
        where += " (not connected)"
    bits = [where]
    if row["default"]:
        bits.append("starts here")
    if row["persistent"]:
        bits.append("always shown")
    if row["app"]:
        bits.append(f"opens {row['app'].split()[0]}")
    return "  ·  ".join(bits)


def title(row: dict) -> str:
    key = row["id"] % 10
    return f"Workspace {row['id']}" + (f"  —  {row['name']}" if row["name"] else "") + f"   (Super+{key})"


# ---- quick layouts -------------------------------------------------------------------------------------------------
def quick_group(win, state: Pending, names: list[str]) -> Adw.PreferencesGroup:
    group = Adw.PreferencesGroup(title="Quick layout",
                                 description="Sets the screen for all ten at once. Names, apps and the rest are kept.")

    def lay_out(pick):
        firsts = set()
        for row in state.rows:
            row["monitor"] = pick(row["id"])
            row["default"] = bool(row["monitor"]) and row["monitor"] not in firsts  # lowest number starts each screen
            firsts.add(row["monitor"])
        win.refresh()

    options = []
    if len(names) > 1:
        options.append(("Alternate between screens", f"1 on {names[0]}, 2 on {names[1]}, 3 on {names[(2) % len(names)]} and so on",
                        lambda n: names[(n - 1) % len(names)]))
        per = -(-workspaces.COUNT // len(names))
        options.append(("Split between screens", f"1–{per} on {names[0]}, then the next ones on {names[1]}",
                        lambda n: names[min((n - 1) // per, len(names) - 1)]))
    for name in names:
        options.append((f"Everything on {name}", "All ten workspaces open on this screen", lambda n, name=name: name))
    options.append(("No fixed screen", "Workspaces open on whichever screen you are on", lambda n: ""))
    for label, sub, pick in options:
        row = Adw.ActionRow(title=label, subtitle=sub, activatable=True, use_markup=False)
        row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        row.connect("activated", lambda _r, pick=pick: lay_out(pick))
        group.add(row)
    return group


# ---- one workspace -----------------------------------------------------------------------------------------------------
def workspace_row(win, state: Pending, row: dict, known: list[str], connected: list[str]) -> Adw.ExpanderRow:
    exp = Adw.ExpanderRow(title=title(row), subtitle=summary(row, connected), use_markup=False,
                          expanded=row["id"] in state.expanded)
    exp.connect("notify::expanded", lambda e, _p: (state.expanded.add if e.get_expanded() else state.expanded.discard)(row["id"]))
    pill = ui.tag("default")
    exp.add_suffix(pill)

    def touched():
        saved = state.saved[row["id"] - 1]
        ui.set_tag(pill, "changed" if row != saved else "default")
        exp.set_title(title(row))
        exp.set_subtitle(summary(row, connected))
        default_sw.set_sensitive(bool(row["monitor"]))
        win.changed()

    # Screen
    choices = [""] + known
    labels = ["Any screen (wherever you are)"] + [n + ("" if n in connected else " (not connected)") for n in known]
    screen = Adw.ActionRow(title="Screen", subtitle="Where this workspace opens.", use_markup=False)
    drop = Gtk.DropDown(model=Gtk.StringList.new(labels), valign=Gtk.Align.CENTER)
    drop.set_selected(choices.index(row["monitor"]) if row["monitor"] in choices else 0)
    screen.add_suffix(drop)
    exp.add_row(screen)

    # Starts here (one per screen)
    starts = Adw.ActionRow(title="Starts here", use_markup=False,
                           subtitle="The workspace this screen shows when you log in. Only one per screen.")
    default_sw = Gtk.Switch(active=row["default"], valign=Gtk.Align.CENTER, sensitive=bool(row["monitor"]))
    starts.add_suffix(default_sw)
    starts.set_activatable_widget(default_sw)
    exp.add_row(starts)

    def picked(d, _p):
        row["monitor"] = choices[d.get_selected()]
        if not row["monitor"]:
            row["default"] = False
            default_sw.set_active(False)
        touched()
    drop.connect("notify::selected", picked)

    def defaulted(sw, _p):
        if sw.get_active() == row["default"]:
            return
        row["default"] = sw.get_active()
        if row["default"]:
            others = [r for r in state.rows if r is not row and r["monitor"] == row["monitor"] and r["default"]]
            for r in others:
                r["default"] = False
            if others:  # their switches and summaries change too
                win.refresh()
                return
        touched()
    default_sw.connect("notify::active", defaulted)

    # Name, always shown, app
    exp.add_row(text_row(row, "name", "Name", "Shown in the bar instead of the number, for example Web or Games.", "No name", touched))
    shown = Adw.ActionRow(title="Always show in the bar", use_markup=False,
                          subtitle="Keeps it in the bar even when nothing is open on it.")
    shown_sw = Gtk.Switch(active=row["persistent"], valign=Gtk.Align.CENTER)
    shown_sw.connect("notify::active", lambda sw, _p: (row.__setitem__("persistent", sw.get_active()), touched()))
    shown.add_suffix(shown_sw)
    shown.set_activatable_widget(shown_sw)
    exp.add_row(shown)
    exp.add_row(text_row(row, "app", "Open when empty", "An app that starts by itself when you switch to this workspace and "
                                                         "it is empty, for example zen-browser or steam.", "Nothing", touched))
    ui.set_tag(pill, "changed" if row != state.saved[row["id"] - 1] else "default")
    return exp


def text_row(row: dict, key: str, label: str, subtitle: str, placeholder: str, touched) -> Adw.ActionRow:
    r = Adw.ActionRow(title=label, subtitle=subtitle, use_markup=False)
    entry = Gtk.Entry(text=row[key], placeholder_text=placeholder, valign=Gtk.Align.CENTER, width_chars=20)

    def edited(e):
        if e.get_text() != row[key]:
            row[key] = e.get_text()
            touched()
    entry.connect("changed", edited)
    r.add_suffix(entry)
    return r
