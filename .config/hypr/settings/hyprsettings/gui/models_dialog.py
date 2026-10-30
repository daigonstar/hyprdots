"""Picking an ollama model: installed ones, suggestions for your GPU, and downloads with a progress bar."""

from __future__ import annotations

import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .. import models  # noqa: E402
from ..schema import BY_ID, Setting  # noqa: E402
from . import ui  # noqa: E402

CAPS: dict[str, set[str]] = {}  # model -> abilities, filled in the background


def choose(win, s: Setting) -> None:
    store = win.store
    vision = s.kind == "vision_model"
    installed, err = models.installed()
    current = store.get(s)[0]
    names = [m["name"] for m in installed]
    sizes = {m["name"]: m["size_gb"] for m in installed}
    tier = models.recommend_tier(models.vram_mib())
    suggested = [models.TIERS[tier][1 if vision else 0]] + [t[1 if vision else 0] for t in models.TIERS.values()]
    chat_model = store.get(BY_ID["assistant.model"])[0]

    dialog = Adw.Dialog(title=s.label, content_width=560, content_height=620)
    page = Adw.PreferencesPage()
    view = Adw.ToolbarView(content=page)
    view.add_top_bar(Adw.HeaderBar())
    dialog.set_child(view)
    intro = Adw.PreferencesGroup(description=s.help + "\n\n" + (err or f"Your GPU suggests the '{tier}' size."))
    page.add(intro)

    notes: dict[str, Gtk.Label] = {}

    def pick(value):
        dialog.close()
        if value == "pull:?":
            ui.ask(win, "Download a model", lambda t: start_pull(win, s, t.strip()), [("Name from ollama.com/library, for example qwen3:8b", "")])
        elif value.startswith("pull:"):
            start_pull(win, s, value[5:])
        else:
            store.stage(s, "" if value == "none" else value)
            win.refresh()

    def add(group, value, title, subtitle="", note_for=None):
        row = Adw.ActionRow(title=title, subtitle=subtitle, activatable=True, use_markup=False)
        if value == (current or "none"):
            row.add_suffix(Gtk.Image(icon_name="object-select-symbolic"))
        if note_for:
            label = Gtk.Label(css_classes=["caption", "dim-label"], wrap=True, xalign=1, max_width_chars=26)
            notes[note_for] = label
            row.add_suffix(label)
        row.connect("activated", lambda _r: pick(value))
        group.add(row)

    have = Adw.PreferencesGroup(title="On this PC")
    page.add(have)
    if vision:
        add(have, "same", "Same as chat model" + (f" ({chat_model})" if chat_model else ""), note_for="same")
        add(have, "none", "None", "Turns image features off")
    for n in names:
        add(have, n, n, f"{sizes[n]} GB", note_for=n)
    get = Adw.PreferencesGroup(title="Download")
    page.add(get)
    for n in dict.fromkeys(x for x in suggested if x and x not in names):
        add(get, f"pull:{n}", n, "suggested for your GPU" if n == models.TIERS[tier][1 if vision else 0] else "popular choice")
    add(get, "pull:?", "Another model…", "Any name from ollama.com/library")

    def describe(name):
        if name == "same":
            seen = CAPS.get(chat_model)
            if seen is None:
                return "checking…"
            return "can read images" if "vision" in seen else "chat model reports no vision support"
        caps = CAPS.get(name)
        if caps is None:
            return "checking…"
        need = "vision" if vision else "tools"
        text = ", ".join(sorted(c for c in caps if c in ("tools", "vision", "thinking"))) or "unknown"
        return text + ("" if need in caps else f"  ·  no {need} support")

    def refresh_notes():
        for name, label in notes.items():
            label.set_label(describe(name))
            label.set_css_classes(["caption", "error-text" if "no " in describe(name) else "dim-label"])
        return False

    def work():
        for n in dict.fromkeys([*names, *([chat_model] if vision and chat_model else [])]):
            if n not in CAPS:
                CAPS[n] = models.capabilities(n)
                GLib.idle_add(refresh_notes)
    refresh_notes()
    threading.Thread(target=work, daemon=True).start()
    dialog.present(win)


def start_pull(win, s: Setting, name: str) -> None:
    if not name:
        raise ValueError("type a model name")
    cancel = threading.Event()
    dialog = Adw.AlertDialog(heading=f"Downloading {name}", body="This can take a while for large models.")
    bar = Gtk.ProgressBar(show_text=True, text="starting…")
    dialog.set_extra_child(bar)
    dialog.add_response("cancel", "Cancel")
    dialog.connect("response", lambda _d, _r: cancel.set())
    dialog.present(win)
    pulse = [GLib.timeout_add(150, lambda: bar.pulse() or True)]

    def progress(status, fraction):
        def show():
            bar.set_text(status)
            if fraction is not None:
                if pulse[0]:
                    GLib.source_remove(pulse[0])
                    pulse[0] = 0
                bar.set_fraction(fraction)
            return False
        GLib.idle_add(show)

    def done(ok, msg):
        if pulse[0]:
            GLib.source_remove(pulse[0])
        if not cancel.is_set():
            dialog.force_close()
        if ok:
            win.store.stage(s, name)
            win.refresh()
            win.toast(f"{msg}. Save to keep it.")
        else:
            win.toast(msg)
        return False

    def work():
        ok, msg = models.pull(name, progress, cancel)
        GLib.idle_add(done, ok, msg)
    threading.Thread(target=work, daemon=True).start()
