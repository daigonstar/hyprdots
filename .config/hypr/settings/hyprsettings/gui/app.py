"""The settings window: page list on the left, the page on the right, a save bar that appears when something
is changed. Ctrl+S saves, Ctrl+Q / Ctrl+W close (asking first if there are unsaved changes)."""

from __future__ import annotations

import shutil
import subprocess
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from .. import overrides, theme  # noqa: E402
from ..schema import BY_ID, CLOUD_EFFECT, PAGE_INTRO, PAGES as SHARED_PAGES, for_page  # noqa: E402
from ..store import Store  # noqa: E402
from . import pages, ui  # noqa: E402

APP_ID = "com.hyprdots.settings"


PAGES = ["User", "Performance", *SHARED_PAGES]  # only in the window: the terminal version has neither

# The sidebar, in groups of what belongs together. A page missing from here still shows, under Other.
SECTIONS = (
    ("You", ("User", "Calendar", "Cloud drives")),
    ("System", ("Network", "Displays", "Performance", "Power & lock")),
    ("Look", ("Theme", "Bar layout", "Launcher")),
    ("Windows and keys", ("Workspaces", "Window rules", "Keybinds", "Hyprland")),
    ("Apps", ("Hyprdots", "File types")),
    ("Hearthling", ("Assistant", "Assistant Monitor")),
)
# Names that say what is on the page; the page keeps its own name for --page=
LABELS = {"Hyprdots": "Default apps", "Assistant Monitor": "Health monitor"}


def sidebar_order() -> list[tuple[str, str]]:
    """(section, page) for every page, in sidebar order."""
    placed = [(section, page) for section, pages in SECTIONS for page in pages if page in PAGES]
    seen = {page for _, page in placed}
    return placed + [("Other", page) for page in PAGES if page not in seen]


# Words people search with that a page's own text may not use (pages built by hand list no settings to search)
KEYWORDS = {
    "User": "password picture photo avatar name account",
    "Performance": "cpu gpu ram memory temperature heat hot boost power limit freeze crash overheating",
    "Network": "wifi wireless ethernet internet vpn dns ip hotspot",
    "Displays": "monitor screen resolution refresh rate hz scale rotate hidpi",
    "Power & lock": "idle sleep suspend lock screen timeout hibernate",
    "Theme": "colour color wallpaper font dark light",
    "Bar layout": "waybar modules panel top bottom",
    "Launcher": "app menu search rofi",
    "Workspaces": "desktop virtual monitor",
    "Window rules": "float fullscreen workspace app opens",
    "Keybinds": "shortcut keys hotkey keyboard",
    "File types": "open with default mime pdf image video browser",
    "Cloud drives": "google drive onedrive dropbox nextcloud webdav rclone",
    "Calendar": "events google ical",
    "Hyprdots": "terminal file manager browser startup autostart super key logo",
}


def _plain(text: str) -> str:
    """Lower case, and Wi-Fi the same as wifi."""
    return text.lower().replace("-", "")


def search_text(page: str) -> str:
    """What the sidebar search looks in: the page's names, its intro, the names of its settings and its keywords."""
    words = [page, LABELS.get(page, ""), PAGE_INTRO.get(page, ""), KEYWORDS.get(page, "")]
    words += [s.label for s in for_page(page)]
    return _plain(" ".join(words))


def builders() -> dict:
    """Page name -> function(win) returning the page widget. Pages that apply live have their own modules."""
    from . import account, barlayout, power, cloud, displays, filetypes, keybinds, network, windowrules, workspaces
    out = {name: (lambda win, name=name: pages.basic_page(win, name)) for name in PAGES}
    out.update({"User": account.build, "Performance": power.build, "Keybinds": keybinds.build, "File types": filetypes.build,
                "Displays": displays.build, "Workspaces": workspaces.build, "Bar layout": barlayout.build, "Cloud drives": cloud.build,
                "Network": network.build, "Window rules": windowrules.build})
    return out


class Window(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, store: Store, page: str | None = None):
        super().__init__(application=app, title="Settings", default_width=1180, default_height=800)
        self.store = store
        self.builders = builders()
        self.page = page if page in PAGES else PAGES[0]
        self.scroll_memory: dict[str, float] = {}
        # Pages whose changes are not in the settings files (Workspaces) put an object here with count(), save() ->
        # (ok, message) and discard(); the save bar, Save, Discard and closing treat them like staged settings.
        self.pending: dict = {}

        # Sidebar: one row per page, in sections, with a search that also finds a page by its settings' names
        self.search = Gtk.SearchEntry(placeholder_text="Search settings", margin_start=10, margin_end=10, margin_top=6, margin_bottom=4)
        self.search.connect("search-changed", lambda _e: self._searched())
        self.search.connect("activate", lambda _e: self._open_first_match())
        self.sidebar_list = Gtk.ListBox(css_classes=["navigation-sidebar"], selection_mode=Gtk.SelectionMode.SINGLE)
        logo = self.store.get(BY_ID["look.super_logo"])[0]
        self.rows, self.section_of, self.find_in = {}, {}, {}
        for section, name in sidebar_order():
            glyph = ui.PAGE_GLYPHS.get(name) or theme.super_glyph("arch" if logo == "text" else logo)
            box = Gtk.Box(spacing=12, margin_top=4, margin_bottom=4, margin_start=4)
            box.append(Gtk.Label(label=glyph, css_classes=["glyph"]))
            box.append(Gtk.Label(label=LABELS.get(name, name), xalign=0))
            row = Gtk.ListBoxRow(child=box, name=name)
            self.rows[name], self.section_of[name], self.find_in[name] = row, section, search_text(name)
            self.sidebar_list.append(row)
        self.sidebar_list.set_header_func(self._section_header)
        self.sidebar_list.set_filter_func(self._matches)
        self.sidebar_list.connect("row-selected", self._on_page)
        self.sidebar_list.connect("row-activated", lambda _l, row: self._pick(row))
        self.picking = False

        side_header = Adw.HeaderBar(show_end_title_buttons=False)
        title = Gtk.Box(spacing=8)
        title.append(Gtk.Label(label=theme.super_glyph("arch" if logo == "text" else logo), css_classes=["glyph"]))
        title.append(Gtk.Label(label="Settings", css_classes=["sidebar-title"]))
        side_header.set_title_widget(title)
        side_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        side_box.append(self.search)
        side_box.append(Gtk.ScrolledWindow(child=self.sidebar_list, hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True))
        side_view = Adw.ToolbarView(content=side_box)
        side_view.add_top_bar(side_header)
        sidebar = Adw.NavigationPage(title="Settings", child=side_view)

        # Content: the page, with the save bar under it
        self.content_view = Adw.ToolbarView()
        self.content_view.add_top_bar(Adw.HeaderBar())
        self.savebar = self._build_savebar()
        self.content_view.add_bottom_bar(self.savebar)
        self.content = Adw.NavigationPage(title=LABELS.get(self.page, self.page), child=self.content_view)

        self.split = Adw.NavigationSplitView(sidebar=sidebar, content=self.content, min_sidebar_width=230, max_sidebar_width=280)
        self.toasts = Adw.ToastOverlay(child=self.split)
        self.set_content(self.toasts)

        # Narrow windows (a phone-sized or rotated tablet screen) show one pane at a time
        bp = Adw.Breakpoint(condition=Adw.BreakpointCondition.parse("max-width: 640sp"))
        bp.add_setter(self.split, "collapsed", True)
        self.add_breakpoint(bp)

        keys = Gtk.ShortcutController(scope=Gtk.ShortcutScope.GLOBAL)
        for accel, fn in (("<Control>s", self.save), ("<Control>q", self.close), ("<Control>w", self.close),
                          ("<Control>f", self.search.grab_focus)):
            keys.add_shortcut(Gtk.Shortcut(trigger=Gtk.ShortcutTrigger.parse_string(accel),
                                           action=Gtk.CallbackAction.new(lambda *_a, fn=fn: fn() or True)))
        self.add_controller(keys)
        self.connect("close-request", self._on_close)

        for w in store.warnings:
            self.toast(w)
        self.sidebar_list.select_row(self._row_for(self.page))

    # ---- pages ------------------------------------------------------------------------------------------------
    def _row_for(self, name: str) -> Gtk.ListBoxRow:
        return self.rows[name]

    def _section_header(self, row: Gtk.ListBoxRow, before: Gtk.ListBoxRow | None) -> None:
        section = self.section_of[row.get_name()]
        if before is not None and self.section_of[before.get_name()] == section:
            row.set_header(None)
            return
        row.set_header(Gtk.Label(label=section, xalign=0, css_classes=["sidebar-section"]))

    def _matches(self, row: Gtk.ListBoxRow) -> bool:
        words = _plain(self.search.get_text()).split()
        return all(w in self.find_in[row.get_name()] for w in words)

    def _searched(self) -> None:
        self.sidebar_list.invalidate_filter()
        self.sidebar_list.invalidate_headers()

    def _pick(self, row: Gtk.ListBoxRow) -> None:
        self.picking = True
        self.sidebar_list.select_row(row)
        self._on_page(self.sidebar_list, row)  # a row already selected does not say so again
        self.picking = False

    def _open_first_match(self) -> None:
        for _, name in sidebar_order():
            if self._matches(self.rows[name]):
                self._pick(self.rows[name])
                return

    def _on_page(self, _list, row) -> None:
        # While a search hides the open page, the list may select another by itself: only a pick changes the page
        if row is None or (self.search.get_text() and not self.picking):
            return
        self._remember_scroll()
        self.page = row.get_name()
        self.content.set_title(LABELS.get(self.page, self.page))
        self._show_page()
        self.split.set_show_content(True)

    def _show_page(self) -> None:
        widget = self.builders[self.page](self)
        self.content_view.set_content(widget)
        self.changed()
        offset = self.scroll_memory.get(self.page)
        if offset and isinstance(widget, Gtk.ScrolledWindow):
            GLib.idle_add(lambda: widget.get_vadjustment().set_value(offset) or False)

    def _remember_scroll(self) -> None:
        widget = self.content_view.get_content()
        if isinstance(widget, Gtk.ScrolledWindow):
            self.scroll_memory[self.page] = widget.get_vadjustment().get_value()

    def refresh(self) -> None:
        """Rebuilds the current page in place (after a reset, a list change or a save), keeping the scroll position."""
        self._remember_scroll()
        self._show_page()

    def toast(self, text: str) -> None:
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=4))

    # ---- saving ----------------------------------------------------------------------------------------------------
    def _build_savebar(self) -> Gtk.Revealer:
        bar = Gtk.Box(spacing=10, css_classes=["savebar"])
        bar.append(Gtk.Image(icon_name="document-save-symbolic"))
        self.savebar_label = Gtk.Label(label="Unsaved changes", xalign=0, hexpand=True)
        bar.append(self.savebar_label)
        discard = Gtk.Button(label="Discard")
        discard.connect("clicked", lambda _b: self.discard())
        save = Gtk.Button(label="Save", css_classes=["suggested-action"], tooltip_text="Ctrl+S")
        save.connect("clicked", lambda _b: self.save())
        bar.append(discard)
        bar.append(save)
        return Gtk.Revealer(child=bar, transition_type=Gtk.RevealerTransitionType.SLIDE_UP)

    @property
    def dirty(self) -> bool:
        return self.store.dirty or any(p.count() for p in self.pending.values())

    def changed(self) -> None:
        n = len(self.store.staged) + sum(p.count() for p in self.pending.values())
        self.savebar_label.set_label(f"{n} unsaved change{'s' if n != 1 else ''}")
        self.savebar.set_reveal_child(self.dirty)

    def discard(self) -> None:
        self.store.reload()
        for p in self.pending.values():
            p.discard()
        self.refresh()
        self.toast("Changes discarded.")

    def save(self, then=None) -> None:
        if not self.dirty:
            self.toast("Nothing to save.")
            return
        for p in [p for p in self.pending.values() if p.count()]:
            ok, msg = p.save()
            if ok:
                self.toast(msg)
            else:
                ui.message(self, "Could not apply", msg)
        if not self.store.dirty:
            self.refresh()
            if then:
                then()
            return
        seen = len(self.store.warnings)
        try:
            effects = self.store.save()
        except Exception as e:  # a failed write must never look like success
            return ui.message(self, "Could not save", str(e))
        self.refresh()
        for w in self.store.warnings[seen:]:
            self.toast(w)
        if CLOUD_EFFECT in effects:
            from . import cloud as cloud_page
            rest = [e for e in effects if e != CLOUD_EFFECT]
            return cloud_page.restart_after_save(self, lambda quiet=False: self._after_save(rest, then, quiet and not rest))
        self._after_save(effects, then)

    def _after_save(self, effects: list[str], then=None, quiet: bool = False) -> None:
        if any("Hyprland" in e for e in effects) and shutil.which("hyprctl"):
            ui.confirm(self, "Reload Hyprland now?", "Your Hyprland changes are saved. Reload now to see them? Windows stay open.",
                       "Reload", lambda: (self.reload_hyprland(), then and then()), no="Later")
            return
        if not quiet:  # quiet: the cloud drive step already said it was saved
            self.toast("Saved." + (" Takes effect " + ", ".join(effects) + "." if effects else ""))
        if then:
            then()

    def reload_hyprland(self) -> None:
        problem = overrides.config_problem()
        if problem:
            ui.message(self, "Not reloaded", "Your running desktop is unchanged. This needs fixing first:\n\n" + problem)
            return
        result = subprocess.run(["hyprctl", "reload"], capture_output=True, text=True)
        errors = subprocess.run(["hyprctl", "configerrors"], capture_output=True, text=True).stdout.strip()
        if errors and errors != "[]":
            ui.message(self, "Hyprland reported a problem", "Hyprland reloaded but reported config errors:\n\n" + errors[:600])
        else:
            self.toast("Hyprland reloaded." if result.returncode == 0 else "Could not reload Hyprland.")

    def _on_close(self, _w) -> bool:
        if not self.dirty:
            return False
        d = Adw.AlertDialog(heading="Save your changes?", body="Some changes are not saved yet.")
        d.add_response("cancel", "Cancel")
        d.add_response("discard", "Discard")
        d.add_response("save", "Save")
        d.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        d.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        d.set_default_response("save")
        d.set_close_response("cancel")

        def answered(_d, r):
            if r == "discard":
                self.store.reload()
                for p in self.pending.values():
                    p.discard()
                self.close()
            elif r == "save":
                self.save(then=self.close)
        d.connect("response", answered)
        d.present(self)
        return True


def main(argv: list[str]) -> int:
    page = next((a.split("=", 1)[1] for a in argv if a.startswith("--page=")), None)
    app = Adw.Application(application_id=APP_ID)

    def show_page(_action, param):
        # A second launch (the bar's network button, say) brings the open window to the front on its page
        wins = app.get_windows()
        if wins and param.get_string() in PAGES:
            wins[0].sidebar_list.select_row(wins[0]._row_for(param.get_string()))
    action = Gio.SimpleAction.new("show-page", GLib.VariantType.new("s"))
    action.connect("activate", show_page)
    app.add_action(action)

    def activate(a):
        # A second launch brings the open window to the front instead of opening another
        if a.get_windows():
            a.get_windows()[0].present()
            return
        from . import theme_override
        from .. import livetheme
        a.live_theme = livetheme.follow(a)  # follows a theme override switch while open
        theme_override.match_scheme()  # dark, or light under a light theme override (XP style)
        provider = Gtk.CssProvider()
        provider.load_from_string(ui.css())
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        Window(a, Store(), page).present()
    app.connect("activate", activate)
    app.register(None)
    if app.get_is_remote() and page:
        app.activate_action("show-page", GLib.Variant("s", page))
    return app.run([sys.argv[0]])
