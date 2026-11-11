#!/usr/bin/env python3
"""Sound: the desktop's audio app. Outputs and inputs, each app's volume and where it plays, sound cards, an
equaliser, a cleaned-up microphone, and a wireless headset's battery and settings, all in one window.

    app.py [--page output|input|apps|devices|headset]

A second start brings the open window forward on that page. It re-reads everything as soon as something changes
(pactl subscribe), and asks the headset for its battery every 30 seconds. pulse.py, filters.py and headset.py do the
work; pages.py, filters_ui.py and headset_ui.py are the pages."""
import sys
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(1, str(Path(__file__).resolve().parent.parent / "settings"))
import filters  # noqa: E402
import headset  # noqa: E402
import pulse  # noqa: E402
from hyprsettings import livetheme  # noqa: E402
import ui  # noqa: E402
from headset_ui import HeadsetPage  # noqa: E402
from pages import AppsPage, DevicesPage, InputPage, OutputPage  # noqa: E402

PAGES = ("output", "input", "apps", "devices", "headset")
HEADSET_SECONDS = 30
REFRESH_AFTER_MS = 120  # a burst of changes (a new app opens several streams) is read once


class Sound(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="com.hyprdots.audio", flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.memory = headset.load()
        self.state = None
        self.headset = []
        self.reading = self.dirty = False
        self.timer = 0
        self.wanted_page = "output"
        self.loopback = pulse.Loopback()
        self.meter = pulse.Meter(lambda v: GLib.idle_add(self._level, v))
        self.watcher = pulse.Watcher(lambda: GLib.idle_add(self.refresh_soon))

    # ---- starting -----------------------------------------------------------------------------------------------------
    def do_command_line(self, line):
        args = line.get_arguments()[1:]
        if "--page" in args[:-1]:
            wanted = args[args.index("--page") + 1]
            self.wanted_page = wanted if wanted in PAGES else "output"
        self.activate()
        return 0

    def do_activate(self):
        win = self.get_active_window()
        if win:
            self._go(self.wanted_page)
            win.present()
            return
        self.live_theme = livetheme.follow(self)  # follows a theme override switch while open
        win = Gtk.ApplicationWindow(application=self, title="Sound", default_width=560, default_height=820)
        win.add_css_class("sound")
        self.look = ui.Look(Gdk.Display.get_default())
        self.output, self.input = OutputPage(self), InputPage(self)
        self.apps, self.devices, self.headset_page = AppsPage(self), DevicesPage(self), HeadsetPage(self)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vexpand=True)
        for name, title, part in (("output", "Output", self.output), ("input", "Input", self.input),
                                  ("apps", "Apps", self.apps), ("devices", "Devices", self.devices),
                                  ("headset", "Headset", self.headset_page)):
            self.stack.add_titled(part.widget, name, title)
        self.stack.get_page(self.headset_page.widget).set_visible(False)
        self.stack.connect("notify::visible-child-name", lambda *_a: self._page_changed())
        top = Gtk.Box(spacing=8, css_classes=["pages"])
        top.append(Gtk.StackSwitcher(stack=self.stack, hexpand=True, halign=Gtk.Align.START))
        self.status = ui.label("", "dim", ellipsize=True)
        self.status.set_hexpand(True)
        self.status.set_xalign(1)
        top.append(self.status)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        body.append(top)
        body.append(self.stack)
        win.set_child(body)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        win.add_controller(keys)
        win.connect("close-request", lambda _w: self._closing() or False)
        win.present()
        self.watcher.start()
        self.refresh()
        self.read_headset()
        GLib.timeout_add_seconds(HEADSET_SECONDS, lambda: self.read_headset() or True)
        self._go(self.wanted_page)

    def _key(self, _c, key, _code, mods):
        if key == Gdk.KEY_Escape:
            self.get_active_window().close()
            return True
        if mods & Gdk.ModifierType.CONTROL_MASK and Gdk.KEY_1 <= key <= Gdk.KEY_5:
            self._go(PAGES[key - Gdk.KEY_1])
            return True
        return False

    def _go(self, name):
        if name == "headset" and not self.stack.get_page(self.headset_page.widget).get_visible():
            name = "output"
        self.stack.set_visible_child_name(name)

    def _closing(self):
        self.loopback.stop()
        self.meter.stop()
        self.watcher.stop()

    # ---- reading ------------------------------------------------------------------------------------------------------
    def refresh_soon(self):
        if not self.timer:
            self.timer = GLib.timeout_add(REFRESH_AFTER_MS, self._refresh_now)
        return False

    def _refresh_now(self):
        self.timer = 0
        self.refresh()
        return False

    def refresh(self):
        if self.reading:
            self.dirty = True  # something changed while reading: read again after
            return
        self.reading = True

        def job():
            state = pulse.snapshot()
            state.update(eq_on=filters.running(filters.EQ_UNIT), mic_on=filters.running(filters.MIC_UNIT),
                         can_clean=filters.can_clean_mic())
            return state
        ui.background(job, self._show)

    def _show(self, state):
        self.reading = False
        eq, mic = self.memory.get("eq", {}), self.memory.get("mic", {})
        state["output"] = pulse.current(state["default_sink"], filters.EQ_NODE, state["eq_on"], eq.get("target"))
        state["input"] = pulse.current(state["default_source"], filters.MIC_NODE, state["mic_on"], mic.get("source"))
        state["hearing"] = self.loopback.running()
        product = self.headset[0]["product"] if self.headset else ""
        state["headset"] = filters.headset_parts(state["sinks"], state["sources"], product) if product else {}
        self.state = state
        for part in (self.output, self.input, self.apps, self.devices):
            part.update(state)
        self._page_changed()
        if self.dirty:
            self.dirty = False
            self.refresh_soon()
        return False

    def read_headset(self):
        ui.background(headset.read, self._show_headset)

    def _show_headset(self, devices):
        self.headset = devices
        shown = self.headset_page.update(devices)
        self.stack.get_page(self.headset_page.widget).set_visible(bool(shown))
        if self.wanted_page == "headset" and shown and self.stack.get_visible_child_name() != "headset":
            self.wanted_page = "output"
            self._go("headset")
        return False

    def _page_changed(self):
        """The input level is only measured while you can see it."""
        if self.state and self.stack.get_visible_child_name() == "input":
            self.meter.watch(self.state["default_source"])
        else:
            self.meter.stop()

    def _level(self, value):
        self.input.level(value)
        return False

    # ---- what the pages call ------------------------------------------------------------------------------------------
    def say(self, text):
        self.status.set_text(text)
        self.status.set_tooltip_text(text)

    def save(self):
        headset.save_own(self.memory)

    def act(self, job, done=None):
        """A change: made off the main loop, then everything re-read (the watcher would too, but this is sooner)."""
        def finished(result):
            if done:
                done(result)
            self.refresh_soon()
            return False
        ui.background(job, finished)

    def describe(self, name, kind="sink"):
        """A device's name as people know it."""
        if name == filters.EQ_NODE:
            return "Equaliser"
        if name == filters.MIC_NODE:
            return "Clean microphone"
        devices = (self.state or {}).get("sinks" if kind == "sink" else "sources", [])
        return next((d["description"] for d in devices if d["name"] == name), name or "None")

    def choose(self, kind, name):
        """Makes an output or input the one in use. With the equaliser or clean microphone on, that filter moves to
        it instead, so it stays in front of what you use."""
        state = self.state or {}
        if kind == "sink" and state.get("eq_on"):
            gains = self.memory.setdefault("eq", {}).get("gains", filters.PRESETS["Flat"])
            self.memory["eq"]["target"] = name
            self.save()
            self.act(lambda: filters.eq_on(gains, name, "Equaliser"),
                     lambda ok: self.say(f"Equaliser now plays into {self.describe(name)}." if ok else
                                         "The equaliser did not move."))
        elif kind == "source" and state.get("mic_on"):
            mic = self.memory.setdefault("mic", {})
            mic["source"] = name
            self.save()
            threshold = mic.get("threshold", 50)
            self.act(lambda: filters.mic_on(name, threshold),
                     lambda ok: self.say(f"Cleaning {self.describe(name, 'source')}." if ok else
                                         "The clean microphone did not move."))
        else:
            self.act(lambda: pulse.set_default(kind, name),
                     lambda _r: self.say(f"Using {self.describe(name, kind)}."))
        if kind == "source" and self.loopback.running():
            self.hear_yourself(True, source=name)

    def equaliser(self, on):
        state = self.state or {}
        target = state.get("output")
        eq = self.memory.setdefault("eq", {})
        gains = filters.clamp(eq.get("gains", filters.PRESETS["Flat"]))
        if on:
            if not target or target == filters.EQ_NODE:
                self.say("There is no output to put the equaliser in front of.")
                return
            eq.update(on=True, target=target)
            self.save()
            self.say("Starting the equaliser…")
            self.act(lambda: filters.eq_on(gains, target, "Equaliser"),
                     lambda ok: self.say("Equaliser on." if ok else
                                         f"The equaliser did not start. See: journalctl --user -u {filters.EQ_UNIT}"))
        else:
            eq["on"] = False
            self.save()
            self.act(lambda: filters.eq_off(eq.get("target") or target), lambda _r: self.say("Equaliser off."))

    def equaliser_changed(self):
        self.save()
        state, eq = self.state or {}, self.memory.get("eq", {})
        if state.get("eq_on") and eq.get("target"):
            gains, target = list(eq["gains"]), eq["target"]
            ui.background(lambda: filters.eq_change(gains, target, "Equaliser"))

    def clean_mic(self, on):
        state = self.state or {}
        mic = self.memory.setdefault("mic", {})
        if on:
            source = state.get("input")
            if not source or source == filters.MIC_NODE:
                self.say("There is no microphone to clean.")
                return
            mic.update(on=True, source=source)
            self.save()
            self.say("Starting the clean microphone…")
            threshold = mic.get("threshold", 50)
            self.act(lambda: filters.mic_on(source, threshold),
                     lambda ok: self.say("Clean microphone on: apps now hear it." if ok else
                                         f"It did not start. See: journalctl --user -u {filters.MIC_UNIT}"))
        else:
            mic["on"] = False
            self.save()
            source = mic.get("source")
            self.act(lambda: filters.mic_off(source), lambda _r: self.say("Clean microphone off."))

    def clean_mic_changed(self):
        self.save()
        state, mic = self.state or {}, self.memory.get("mic", {})
        if state.get("mic_on") and mic.get("source"):
            source, threshold = mic["source"], mic.get("threshold", 50)

            def job():
                filters.write(filters.MIC_CONF, filters.mic_conf(source, threshold))  # for its next start
                filters.set_live(filters.MIC_NODE + ".in", {"rnnoise:VAD Threshold (%)": float(threshold)})
            ui.background(job)

    def hear_yourself(self, on, source=None):
        state = self.state or {}
        if on:
            source = source or state.get("default_source")
            sink = state.get("default_sink")
            worked = bool(source and sink) and self.loopback.start(source, sink)
            self.say("You can hear your microphone now. Mind the feedback on speakers." if worked else
                     "Could not play the microphone back.")
        else:
            self.loopback.stop()
        self.refresh_soon()


if __name__ == "__main__":
    sys.exit(Sound().run(sys.argv))
