"""The Sound app's pages for the PC's sound: Output, Input, Apps and Devices. Each has update(state), called whenever
anything changes; ctl (the app) does the changing. GTK only."""
from gi.repository import Gtk

import filters
import pulse
import ui
from filters_ui import CleanMicCard, EqCard

HINTS = {"chat": "The headset's second output, for voice chat. Its ChatMix dial balances it against Game."}


class DeviceRow(Gtk.Box):
    """One output or input: pick it, its volume and mute, and its port when it has more than one."""

    def __init__(self, ctl, kind, name, group):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2, css_classes=["device"])
        self.ctl, self.kind, self.name = ctl, kind, name
        top = Gtk.Box(spacing=8)
        self.pick = Gtk.CheckButton(group=group, hexpand=True)
        self.title = ui.label("", "name", ellipsize=True)
        self.pick.set_child(self.title)
        self.pick.connect("toggled", lambda b: b.get_active() and not self.quiet and ctl.choose(kind, name))
        top.append(self.pick)
        self.port = ui.Choice(lambda port: ctl.act(lambda: pulse.set_port(kind, name, port)))
        self.port.set_hexpand(False)
        top.append(self.port)
        self.append(top)
        self.volume = ui.Volume(lambda v: ctl.act(lambda: pulse.set_volume(kind, name, v)),
                                lambda m: ctl.act(lambda: pulse.set_mute(kind, name, m)), microphone=kind == "source")
        self.volume.set_margin_start(28)
        self.append(self.volume)
        self.hint = ui.label("", "dim", wrap=True)
        self.hint.set_margin_start(28)
        self.append(self.hint)
        self.quiet = False

    def update(self, device, in_use, hint=""):
        self.quiet = True
        self.title.set_text(device["description"])
        self.pick.set_active(in_use)
        (self.add_css_class if in_use else self.remove_css_class)("current")
        self.volume.set(device["volume"], device["mute"])
        ports = [(n, d + ("" if available else " (not plugged in)")) for n, d, available in device["ports"]]
        self.port.set_visible(len(ports) > 1)
        if len(ports) > 1:
            self.port.show(ports, device["port"])
        self.hint.set_text(hint)
        self.hint.set_visible(bool(hint))
        self.quiet = False


class DeviceList(Gtk.Box):
    def __init__(self, ctl, kind):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.group = Gtk.CheckButton()  # the radio group; never shown
        self.rows = ui.Keyed(self, lambda name: DeviceRow(ctl, kind, name, self.group))

    def update(self, devices, in_use, hints=None):
        hints = hints or {}
        for row, device in zip(self.rows.show(d["name"] for d in devices), devices):
            row.update(device, device["name"] == in_use, hints.get(device["name"], ""))


class OutputPage:
    def __init__(self, ctl):
        self.ctl = ctl
        box, _head = ui.card("Output", "Where sound plays. Apps that you have not sent somewhere else follow it.")
        self.devices = DeviceList(ctl, "sink")
        box.append(self.devices)
        self.eq = EqCard(ctl)
        self.widget, _inner = ui.page(box, self.eq)

    def update(self, state):
        outs = pulse.outputs(state["sinks"])
        chat = state.get("headset", {}).get("chat")
        self.devices.update(outs, state["output"], {chat: HINTS["chat"]} if chat else None)
        self.eq.update(state["eq_on"], self.ctl.describe(state["output"]))


class InputPage:
    def __init__(self, ctl):
        self.ctl = ctl
        box, _head = ui.card("Input", "The microphone apps use, unless you sent one somewhere else.")
        meter_row = Gtk.Box(spacing=10)
        meter_row.append(ui.label("Level", "dim"))
        self.meter = Gtk.LevelBar(min_value=0, max_value=1, value=0, hexpand=True, valign=Gtk.Align.CENTER,
                                  css_classes=["meter"])
        for offset in (Gtk.LEVEL_BAR_OFFSET_LOW, Gtk.LEVEL_BAR_OFFSET_HIGH, Gtk.LEVEL_BAR_OFFSET_FULL):
            self.meter.remove_offset_value(offset)
        meter_row.append(self.meter)
        self.meter_what = ui.label("", "dim")
        meter_row.append(self.meter_what)
        box.append(meter_row)
        self.devices = DeviceList(ctl, "source")
        box.append(self.devices)
        hear = Gtk.Box(spacing=10, tooltip_text="Plays your microphone back to you, to hear how you sound. It stops "
                                                "when you close this window.")
        words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        words.append(ui.label("Hear yourself"))
        words.append(ui.label("Your microphone, played to your output", "dim"))
        hear.append(words)
        self.hear = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.hear.connect("notify::active", lambda s, _p: self.quiet or ctl.hear_yourself(s.get_active()))
        hear.append(self.hear)
        box.append(hear)
        self.clean = CleanMicCard(ctl)
        self.widget, _inner = ui.page(box, self.clean)
        self.quiet = False

    def update(self, state):
        self.devices.update(pulse.inputs(state["sources"]), state["input"])
        self.meter_what.set_text("Clean microphone" if state["default_source"] == filters.MIC_NODE else "")
        self.quiet = True
        self.hear.set_active(state["hearing"])
        self.quiet = False
        self.clean.update(state["mic_on"], state["can_clean"], self.ctl.describe(state["input"], "source"))

    def level(self, value):
        self.meter.set_value(pulse.meter_level(value))
        (self.meter.add_css_class if value >= 0.98 else self.meter.remove_css_class)("hot")


class StreamRow(Gtk.Box):
    """One app playing or recording: its volume and mute, and where it goes."""

    def __init__(self, ctl, kind, index):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2, css_classes=["device"])
        self.kind, self.index = kind, index
        top = Gtk.Box(spacing=8)
        self.icon = Gtk.Image(pixel_size=22)
        top.append(self.icon)
        words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        self.app = ui.label("", "name", ellipsize=True)
        self.title = ui.label("", "dim", ellipsize=True)
        words.append(self.app)
        words.append(self.title)
        top.append(words)
        self.target = ui.Choice(lambda device: ctl.act(lambda: pulse.move_stream(kind, index, device)))
        self.target.set_hexpand(False)
        self.target.set_size_request(170, -1)
        top.append(self.target)
        self.append(top)
        self.volume = ui.Volume(lambda v: ctl.act(lambda: pulse.set_stream_volume(kind, index, v)),
                                lambda m: ctl.act(lambda: pulse.set_stream_mute(kind, index, m)),
                                microphone=kind == "source-output")
        self.volume.set_margin_start(30)
        self.append(self.volume)

    def update(self, stream, choices, current):
        theme = Gtk.IconTheme.get_for_display(self.get_display())
        name = stream["icon"] if stream["icon"] and theme.has_icon(stream["icon"]) else "application-x-executable"
        self.icon.set_from_icon_name(name)
        self.app.set_text(stream["app"])
        self.title.set_text(stream["title"] + (" (paused)" if stream["corked"] else ""))
        self.title.set_visible(bool(self.title.get_text()))
        self.target.show(choices, current)
        self.volume.set(stream["volume"], stream["mute"])


class StreamList(Gtk.Box):
    def __init__(self, ctl, kind, empty):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.kind = kind
        self.empty = ui.label(empty, "dim")
        self.append(self.empty)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.append(self.list)
        self.rows = ui.Keyed(self.list, lambda index: StreamRow(ctl, kind, index))

    def update(self, streams, devices, describe):
        by_index = {d["index"]: d["name"] for d in devices}
        choices = [(d["name"], describe(d["name"])) for d in devices]
        self.empty.set_visible(not streams)
        for row, stream in zip(self.rows.show(s["index"] for s in streams), streams):
            row.update(stream, choices, by_index.get(stream["device"]))


class AppsPage:
    def __init__(self, ctl):
        self.ctl = ctl
        playing, _h = ui.card("Playing", "Each app's own volume, and which output it plays to.")
        self.playing = StreamList(ctl, "sink-input", "Nothing is playing.")
        playing.append(self.playing)
        recording, _h = ui.card("Recording", "Apps using a microphone, and which one.")
        self.recording = StreamList(ctl, "source-output", "No app is using a microphone.")
        recording.append(self.recording)
        self.widget, _inner = ui.page(playing, recording)

    def update(self, state):
        outs = [s for s in state["sinks"] if not s["ours"] or s["name"] == filters.EQ_NODE]
        ins = [s for s in state["sources"] if not s["monitor"]]
        self.playing.update(state["playing"], outs, self.ctl.describe)
        self.recording.update(state["recording"], ins, lambda n: self.ctl.describe(n, "source"))


class CardRow(Gtk.Box):
    def __init__(self, ctl, name):
        super().__init__(spacing=10, css_classes=["device"])
        self.title = ui.label("", "name", ellipsize=True)
        self.title.set_hexpand(True)
        self.append(self.title)
        self.profile = ui.Choice(lambda profile: ctl.act(lambda: pulse.set_profile(name, profile)))
        self.profile.set_hexpand(False)
        self.profile.set_size_request(240, -1)
        self.append(self.profile)

    def update(self, card):
        self.title.set_text(card["description"])
        self.title.set_tooltip_text(card["description"])
        self.profile.show(card["profiles"], card["profile"])


class DevicesPage:
    def __init__(self, ctl):
        box, _h = ui.card("Sound cards", "How each card works: which outputs and inputs it offers. Turn one Off to "
                                         "hide a card you never use, such as a screen's HDMI sound.")
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.append(self.list)
        self.rows = ui.Keyed(self.list, lambda name: CardRow(ctl, name))
        self.widget, _inner = ui.page(box)

    def update(self, state):
        cards = state["cards"]
        for row, card in zip(self.rows.show(c["name"] for c in cards), cards):
            row.update(card)
