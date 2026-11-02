"""Window rules page: every rule with a switch, and a step-by-step wizard for adding or changing one. Edits wait for Save
like the other settings; saving writes window_rules_local.lua and reloads Hyprland."""

from __future__ import annotations

import copy

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk  # noqa: E402

from .. import displays, windowrules  # noqa: E402
from ..schema import PAGE_INTRO  # noqa: E402
from . import ui  # noqa: E402

KEY = "Window rules"
WORKSPACES = 10
STEPS = ("Which window?", "What should happen?", "Check and save")


class Pending:
    def __init__(self, directory):
        self.shipped_path = directory / "window_rules.lua"
        self.local_path = directory / "window_rules_local.lua"
        self.reload()

    def reload(self) -> None:
        try:
            self.shipped = windowrules.read_shipped(self.shipped_path)
        except (OSError, ValueError):
            self.shipped = []
        self.saved = windowrules.read_local(self.local_path)
        self.local = copy.deepcopy(self.saved)

    def count(self) -> int:
        return int(self.local != self.saved)

    def save(self) -> tuple[bool, str]:
        previous = self.local_path.read_text(encoding="utf-8") if self.local_path.exists() else None
        try:
            windowrules.write_local(self.local_path, self.local)
        except OSError as e:
            return False, f"Could not save your rules: {e}"
        ok, msg = windowrules.apply()
        if not ok:  # do not leave Hyprland starting up on a rule it refused
            if previous is None:
                self.local_path.unlink(missing_ok=True)
            else:
                self.local_path.write_text(previous, encoding="utf-8")
            windowrules.apply()
            return False, msg
        self.reload()
        return True, "Window rules saved. " + msg

    def discard(self) -> None:
        self.reload()

    def names(self) -> set[str]:
        return {r["name"] for r in self.shipped} | {r.get("name", "") for r in self.local["rules"]}


def build(win) -> Gtk.Widget:
    if KEY not in win.pending:
        win.pending[KEY] = Pending(win.store.dir)
    state: Pending = win.pending[KEY]
    scroller, column = ui.page_box(PAGE_INTRO[KEY])

    add = Gtk.Button(label="Add a rule", halign=Gtk.Align.START, css_classes=["suggested-action", "pill"])
    add.connect("clicked", lambda _b: Wizard(win, state).present())
    column.append(add)

    listed = windowrules.entries(state.shipped, state.local)
    yours = Adw.PreferencesGroup(title="Your rules")
    mine = [e for e in listed if e["kind"] == "yours"]
    if not mine:
        yours.set_description("None yet. Add one to send an app to a workspace, make it float, and more.")
    for entry in mine:
        yours.add(rule_row(win, state, entry))
    column.append(yours)
    built_in = Adw.PreferencesGroup(title="Built in", description="These came with the desktop. Switch one off or change it; "
                                                                  "an update will not undo that.")
    for entry in (e for e in listed if e["kind"] != "yours"):
        built_in.add(rule_row(win, state, entry))
    column.append(built_in)
    return scroller


def rule_row(win, state: Pending, entry: dict) -> Adw.ActionRow:
    rule = entry["rule"]
    row = Adw.ActionRow(title=windowrules.describe_match(rule.get("match", {})), subtitle=windowrules.summary(rule),
                        use_markup=False, activatable=True)
    row.connect("activated", lambda _r: Wizard(win, state, rule).present())
    if entry["kind"] == "changed":
        pill = ui.tag("yours")
        row.add_suffix(pill)
        back = Gtk.Button(icon_name="edit-undo-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Put back the built-in rule",
                          css_classes=["flat"])
        back.connect("clicked", lambda _b: (windowrules.remove_rule(state.local, rule["name"]), win.changed(), win.refresh()))
        row.add_suffix(back)
    elif entry["kind"] == "yours":
        remove = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Delete this rule",
                            css_classes=["flat"])
        remove.connect("clicked", lambda _b: (windowrules.remove_rule(state.local, rule["name"]), win.changed(), win.refresh()))
        row.add_suffix(remove)
    switch = Gtk.Switch(active=entry["on"], valign=Gtk.Align.CENTER, tooltip_text="Use this rule")

    def toggled(sw, _p):
        windowrules.set_on(state.local, rule["name"], sw.get_active())
        win.changed()
    switch.connect("notify::active", toggled)
    row.add_suffix(switch)
    row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
    return row


def window_icon(window_class: str) -> Gtk.Image:
    """The app's icon, from its desktop file when it has one."""
    for name in (window_class, window_class.lower()):
        try:
            info = Gio.DesktopAppInfo.new(f"{name}.desktop")
        except TypeError:
            info = None
        if info and info.get_icon():
            return Gtk.Image(gicon=info.get_icon(), pixel_size=32)
    return Gtk.Image(icon_name="application-x-executable", pixel_size=32)


class Wizard:
    """Three steps, one screen each. Works on a copy of the choices, so Cancel leaves everything as it was."""

    def __init__(self, win, state: Pending, rule: dict | None = None):
        self.win, self.state, self.rule = win, state, rule
        self.c = windowrules.choices_from_rule(rule)
        self.step = 0
        self.dialog = Adw.Dialog(title="Change this rule" if rule else "Add a window rule", content_width=580, content_height=720)
        view = Adw.ToolbarView()
        header = Adw.HeaderBar(show_end_title_buttons=False)
        self.back = Gtk.Button(label="Cancel")
        self.back.connect("clicked", lambda _b: self.go(-1))
        self.next = Gtk.Button(label="Next", css_classes=["suggested-action"])
        self.next.connect("clicked", lambda _b: self.go(1))
        header.pack_start(self.back)
        header.pack_end(self.next)
        view.add_top_bar(header)
        self.progress = Gtk.Label(xalign=0, margin_start=18, margin_top=6, margin_bottom=2, css_classes=["heading"])
        view.add_top_bar(self.progress)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT, vexpand=True)
        self.stack.add_named(self._which_page(), "0")
        self.stack.add_named(self._what_page(), "1")
        self.review_box = Adw.PreferencesPage()
        self.stack.add_named(self.review_box, "2")
        view.set_content(self.stack)
        self.dialog.set_child(view)
        self._show_step()

    def present(self) -> None:
        self.dialog.present(self.win)

    def go(self, by: int) -> None:
        if by < 0 and self.step == 0:
            self.dialog.close()
        elif by > 0 and self.step == len(STEPS) - 1:
            self._finish()
        else:
            self.step += by
            if self.step == 2:
                self._fill_review()
            self._show_step()

    def _show_step(self) -> None:
        self.stack.set_visible_child_name(str(self.step))
        self.progress.set_label(f"Step {self.step + 1} of {len(STEPS)}: {STEPS[self.step]}")
        self.back.set_label("Cancel" if self.step == 0 else "Back")
        self.next.set_label(("Save rule" if self.rule else "Add rule") if self.step == len(STEPS) - 1 else "Next")
        self._check()

    def _check(self) -> None:
        ok = {0: windowrules.has_target(self.c), 1: windowrules.has_effect(self.c), 2: True}[self.step]
        self.next.set_sensitive(ok)

    # ---- step 1 ---------------------------------------------------------------------------------------------------
    def _which_page(self) -> Gtk.Widget:
        page = Adw.PreferencesPage()
        self.open_group = Adw.PreferencesGroup(title="Pick an open window", description="Open the app first if it is not here.")
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                             tooltip_text="Look again")
        refresh.connect("clicked", lambda _b: self._list_windows())
        self.open_group.set_header_suffix(refresh)
        self.open_rows = []
        page.add(self.open_group)
        self._list_windows()

        typed = Adw.PreferencesGroup(title="Or type it", description="The class is the app's internal name. You can use either "
                                                                     "or both, and both must then match.")
        self.class_entry = self._match_row(typed, "App class", "class_kind", "class")
        self.title_entry = self._match_row(typed, "Window title", "title_kind", "title")
        page.add(typed)
        return page

    def _match_row(self, group, label: str, kind_key: str, text_key: str) -> Adw.EntryRow:
        entry = Adw.EntryRow(title=label, text=self.c[text_key], use_markup=False)
        kinds = [k for k, _w in windowrules.KINDS]
        drop = Gtk.DropDown(model=Gtk.StringList.new([w for _k, w in windowrules.KINDS]), valign=Gtk.Align.CENTER)
        drop.set_selected(kinds.index(self.c[kind_key]))

        def kind_changed(d, _p):
            self.c[kind_key] = kinds[d.get_selected()]
        drop.connect("notify::selected", kind_changed)
        entry.add_suffix(drop)

        def text_changed(e):
            self.c[text_key] = e.get_text()
            self._check()
        entry.connect("changed", text_changed)
        group.add(entry)
        return entry

    def _list_windows(self) -> None:
        for row in self.open_rows:
            self.open_group.remove(row)
        self.open_rows = []
        for window in windowrules.open_windows():
            row = Adw.ActionRow(title=windowrules.app_name(window["class"]), subtitle=window["title"], use_markup=False,
                                activatable=True, subtitle_lines=1)
            row.add_prefix(window_icon(window["class"]))
            row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            row.connect("activated", lambda _r, w=window: self._picked(w))
            self.open_group.add(row)
            self.open_rows.append(row)

    def _picked(self, window: dict) -> None:
        """Every window of that app, which is nearly always what you mean: titles change as you use an app."""
        self.c["class_kind"], self.c["class"] = "exact", window["class"]
        self.class_entry.set_text(window["class"])
        self.c["title"] = ""
        self.title_entry.set_text("")
        self.go(1)

    # ---- step 2 ---------------------------------------------------------------------------------------------------
    def _what_page(self) -> Gtk.Widget:
        page = Adw.PreferencesPage()
        where = Adw.PreferencesGroup(title="Where it opens")
        spaces = [""] + [str(n) for n in range(1, WORKSPACES + 1)]
        labels = ["Wherever you are"] + [f"Workspace {n}" for n in spaces[1:]]
        if self.c["workspace"] and self.c["workspace"] not in spaces:
            spaces.append(self.c["workspace"])
            labels.append(self.c["workspace"])
        self.silent = self._switch("Stay where you are", "It opens there, but your screen does not jump to it.", "silent")
        where.add(self._combo("Workspace", "workspace", spaces, labels, lambda: self.silent.set_sensitive(bool(self.c["workspace"]))))
        self.silent.set_sensitive(bool(self.c["workspace"]))
        where.add(self.silent)
        names = [m["name"] for m in displays.read() if not m["disabled"]]
        if self.c["monitor"] and self.c["monitor"] not in names:
            names.append(self.c["monitor"])
        where.add(self._combo("Screen", "monitor", [""] + names, ["Wherever you are"] + names))
        page.add(where)

        how = Adw.PreferencesGroup(title="How it opens")
        self.center = self._switch("In the middle of the screen", None, "center")
        self.pin = self._switch("Show on every workspace", "It follows you when you switch.", "pin")
        self.width = self._spin("Width", "In pixels. Leave at 0 to let the app choose.", "width")
        self.height = self._spin("Height", None, "height")

        def shape_changed():
            floats = self.c["shape"] == "float"
            for row in (self.center, self.pin, self.width, self.height):
                row.set_visible(floats)
        how.add(self._combo("Window", "shape", list(windowrules.SHAPES),
                            ["Normal (tiled)", "Floating", "Fullscreen", "Maximised"], shape_changed))
        for row in (self.center, self.width, self.height, self.pin):
            how.add(row)
        shape_changed()
        page.add(how)

        extras = Adw.PreferencesGroup(title="Extras")
        see = Adw.SpinRow.new_with_range(10, 100, 5)
        see.set_title("Opacity")
        see.set_subtitle("100% is solid. Lower lets the desktop show through.")
        see.set_value(self.c["opacity"])

        def see_changed(s, _p):
            self.c["opacity"] = int(s.get_value())
            self._check()
        see.connect("notify::value", see_changed)
        extras.add(see)
        extras.add(self._switch("Keep the screen awake", "While this window is open, the screen does not turn off or lock.", "awake"))
        extras.add(self._switch("Do not take focus", "You keep typing in what you were using.", "no_focus"))
        extras.add(self._switch("No border", None, "no_border"))
        extras.add(self._switch("Lower lag for games", "Allows tearing while this window is fullscreen.", "immediate"))
        page.add(extras)
        return page

    def _switch(self, title: str, subtitle: str | None, key: str) -> Adw.SwitchRow:
        row = Adw.SwitchRow(title=title, active=self.c[key], use_markup=False)
        if subtitle:
            row.set_subtitle(subtitle)

        def changed(r, _p):
            self.c[key] = r.get_active()
            self._check()
        row.connect("notify::active", changed)
        return row

    def _spin(self, title: str, subtitle: str | None, key: str) -> Adw.SpinRow:
        row = Adw.SpinRow.new_with_range(0, 7680, 10)
        row.set_title(title)
        if subtitle:
            row.set_subtitle(subtitle)
        row.set_value(self.c[key])

        def changed(r, _p):
            self.c[key] = int(r.get_value())
            self._check()
        row.connect("notify::value", changed)
        return row

    def _combo(self, title: str, key: str, values: list[str], labels: list[str], then=None) -> Adw.ComboRow:
        row = Adw.ComboRow(title=title, model=Gtk.StringList.new(labels), use_markup=False)
        row.set_selected(values.index(self.c[key]) if self.c[key] in values else 0)

        def changed(r, _p):
            self.c[key] = values[r.get_selected()]
            if then:
                then()
            self._check()
        row.connect("notify::selected", changed)
        return row

    # ---- step 3 ---------------------------------------------------------------------------------------------------
    def _fill_review(self) -> None:
        if not self.c["name"]:
            wanted = self.c["class"] or self.c["title"] or "rule"
            self.c["name"] = windowrules.unique_name(wanted, self.state.names())
        rule = windowrules.rule_from_choices(self.c)
        new = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(title="This rule will do", description="It applies when the window opens, so close and "
                                                                            "reopen one that is already open.")
        who = Adw.ActionRow(title=windowrules.describe_match(rule["match"]), subtitle="The window", use_markup=False,
                            css_classes=["property"])
        group.add(who)
        for effect in windowrules.describe_effects(rule):
            row = Adw.ActionRow(title=effect[0].upper() + effect[1:], use_markup=False)
            row.add_prefix(Gtk.Image(icon_name="object-select-symbolic"))
            group.add(row)
        new.add(group)
        overlaps = [e for e in windowrules.entries(self.state.shipped, self.state.local)
                    if e["on"] and e["rule"].get("name") != self.c["name"] and e["rule"].get("match") == rule["match"]]
        if overlaps:
            note = Adw.PreferencesGroup(title="Also applies to this window")
            for entry in overlaps:
                note.add(Adw.ActionRow(title=windowrules.summary(entry["rule"]), subtitle="Another rule. If both set the same "
                                       "thing, the one listed later wins.", use_markup=False))
            new.add(note)
        self.stack.remove(self.review_box)
        self.review_box = new
        self.stack.add_named(new, "2")

    def _finish(self) -> None:
        windowrules.put_rule(self.state.local, windowrules.rule_from_choices(self.c))
        self.dialog.close()
        self.win.changed()
        self.win.refresh()
        self.win.toast("Click Save to use this rule.")
