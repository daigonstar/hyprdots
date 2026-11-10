"""The equaliser and Clean microphone cards. filters.py does the work; these follow the output and input in use, which
the app (ctl) knows. GTK only."""
from gi.repository import GLib, Gtk

import filters
import ui

BAND_AFTER_MS = 120  # a band slider changes the sound once it pauses this long


class EqCard(Gtk.Box):
    def __init__(self, ctl):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.ctl, self.quiet, self.timer = ctl, False, 0
        box, head = ui.card("Equaliser", "Shapes everything that plays through the output you use. Boosts lower the "
                                         "overall level a little, so loud bass does not distort.")
        self.switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.switch.connect("notify::active", lambda s, _p: self.quiet or self.ctl.equaliser(s.get_active()))
        head.append(self.switch)
        self.target = ui.label("", "dim", wrap=True)
        box.append(self.target)
        row = Gtk.Box(spacing=8)
        row.append(ui.label("Preset"))
        self.presets = Gtk.DropDown.new_from_strings(list(filters.PRESETS) + [filters.CUSTOM])
        self.presets.set_hexpand(True)
        self.presets.connect("notify::selected", lambda d, _p: self.quiet or self._preset(d.get_selected()))
        row.append(self.presets)
        box.append(row)
        self.curve = Gtk.DrawingArea(css_classes=["eq-curve"], hexpand=True)
        self.curve.set_draw_func(self._draw)
        box.append(self.curve)
        bands = Gtk.Box(homogeneous=True)
        self.bands = []
        for i, (_freq, name) in enumerate(filters.BANDS):
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, -filters.GAIN_LIMIT, filters.GAIN_LIMIT, 0.5)
            scale.set_inverted(True)
            scale.set_size_request(-1, 170)
            scale.add_css_class("eq")
            scale.set_draw_value(False)
            scale.connect("value-changed", lambda s, i=i: self.quiet or self._band(i, s.get_value()))
            col.append(scale)
            col.append(ui.label(name, "band", "dim", xalign=0.5))
            bands.append(col)
            self.bands.append(scale)
        box.append(bands)
        self.room = ui.label("", "dim")
        box.append(self.room)
        self.append(box)

    def memory(self):
        eq = self.ctl.memory.setdefault("eq", {})
        eq["gains"] = filters.clamp(eq.get("gains", filters.PRESETS["Flat"]))
        return eq

    def update(self, on, output_name):
        self.quiet = True
        self.switch.set_active(on)
        self.target.set_text(f"{'Playing into' if on else 'For'}: {output_name}")
        if not self.timer:
            for scale, gain in zip(self.bands, self.memory()["gains"]):
                scale.set_value(gain)
        self.quiet = False
        self._show()

    def _show(self):
        gains = self.memory()["gains"]
        names = list(filters.PRESETS) + [filters.CUSTOM]
        self.quiet, was = True, self.quiet
        self.presets.set_selected(names.index(filters.preset_of(gains)))
        self.quiet = was
        room = filters.headroom_db(gains)
        self.room.set_text(f"Level lowered {room:g} dB to make room for the boost" if room else "")
        self.curve.queue_draw()

    def _draw(self, area, cr, width, height):
        colour = area.get_color()
        gains = self.memory()["gains"]
        top, span = filters.GAIN_LIMIT, 2 * filters.GAIN_LIMIT
        cr.set_source_rgba(colour.red, colour.green, colour.blue, 0.18)
        cr.set_line_width(1)
        cr.move_to(0, height / 2)
        cr.line_to(width, height / 2)
        cr.stroke()
        low, high = 20, 20000
        cr.set_source_rgba(colour.red, colour.green, colour.blue, 0.9 if self.switch.get_active() else 0.45)
        cr.set_line_width(2)
        for x in range(0, int(width) + 1, 2):
            freq = low * (high / low) ** (x / max(width, 1))
            y = (top - max(-top, min(top, filters.response(gains, freq)))) / span * height
            (cr.move_to if x == 0 else cr.line_to)(x, y)
        cr.stroke()

    def _preset(self, index):
        names = list(filters.PRESETS)
        if index >= len(names):
            return  # Custom: nothing to load
        gains = filters.clamp(filters.PRESETS[names[index]])
        self.memory()["gains"] = gains
        self.quiet = True
        for scale, gain in zip(self.bands, gains):
            scale.set_value(gain)
        self.quiet = False
        self._show()
        self.ctl.equaliser_changed()

    def _band(self, i, value):
        gains = list(self.memory()["gains"])
        gains[i] = round(value * 2) / 2
        self.memory()["gains"] = filters.clamp(gains)
        self._show()
        if self.timer:
            GLib.source_remove(self.timer)

        def send():
            self.timer = 0
            self.ctl.equaliser_changed()
            return False
        self.timer = GLib.timeout_add(BAND_AFTER_MS, send)


class CleanMicCard(Gtk.Box):
    def __init__(self, ctl):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.ctl, self.quiet, self.timer = ctl, False, 0
        box, head = ui.card("Clean microphone", "Takes out keyboards, fans and background noise before anyone hears "
                                                "it. Apps get a new microphone, Clean microphone, which is made the one "
                                                "in use.")
        self.switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.switch.connect("notify::active", lambda s, _p: self.quiet or self.ctl.clean_mic(s.get_active()))
        head.append(self.switch)
        self.source = ui.label("", "dim", wrap=True)
        box.append(self.source)
        row = Gtk.Box(spacing=8, tooltip_text="How sure it has to be that you are talking. Higher cuts more noise, "
                                              "but can clip the start of words.")
        row.append(ui.label("Strength"))
        self.strength = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 10, 95, 5)
        self.strength.set_hexpand(True)
        self.strength.set_draw_value(True)
        self.strength.set_value_pos(Gtk.PositionType.RIGHT)
        self.strength.set_format_value_func(lambda _s, v: f"{v:.0f}%")
        self.strength.set_value(self.memory().get("threshold", 50))
        self.strength.connect("value-changed", lambda s: self.quiet or self._strength())
        row.append(self.strength)
        box.append(row)
        self.missing = ui.label("Needs the RNNoise plugin: sudo pacman -S noise-suppression-for-voice", "attention",
                                wrap=True)
        self.missing.set_selectable(True)
        box.append(self.missing)
        self.append(box)

    def memory(self):
        return self.ctl.memory.setdefault("mic", {})

    def update(self, on, can, input_name):
        self.quiet = True
        self.switch.set_active(on)
        self.switch.set_sensitive(can)
        self.strength.set_sensitive(can)
        self.missing.set_visible(not can)
        self.source.set_text(f"{'Cleaning' if on else 'Would clean'}: {input_name}")
        self.quiet = False

    def _strength(self):
        if self.timer:
            GLib.source_remove(self.timer)

        def send():
            self.timer = 0
            self.memory()["threshold"] = round(self.strength.get_value())
            self.ctl.clean_mic_changed()
            return False
        self.timer = GLib.timeout_add(500, send)
