"""The Sound app's Headset page: a wireless headset's battery and charging, its ChatMix dial and the settings it
takes, through headsetcontrol (headset.py). Shown only when a headset is found. GTK only."""
from gi.repository import GLib, Gtk

import headset
import ui

SEND_AFTER_MS = 350

CHARGING_HELP = """The Arctis 7 charges through the micro-USB port on its left ear cup, not through the wireless dongle. \
The dongle plugged into the PC only carries sound, so a headset that sits next to the PC on the dongle alone never charges.

The headset never tells the PC whether it is charging: this window works it out from the battery level, which has to \
climb a couple of percent with the headset switched on before it says "Charging". With the headset off it cannot be \
read at all; that is normal and it still charges.

If it really does not charge:
• The port sits deep in the ear cup. Cables with a thick plug do not reach far enough to make contact. Try a slim plug, \
pushed all the way in.
• A worn micro-USB cable is the most common cause. Try another one; a charge-only cable is fine for this.
• Use a port on the back of the PC or a phone charger, rather than a front-panel port, an unpowered hub or a keyboard's \
pass-through port.
• The light on the headset should change when you plug it in. If it never does with several cables, the port or the \
battery has worn out (the battery cannot be checked from the PC)."""


class HeadsetPage:
    def __init__(self, ctl):
        self.ctl, self.device, self.controls_for, self.timers = ctl, None, None, {}
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["card"])
        self.name = ui.label("Headset", "title")
        box.append(self.name)
        row = Gtk.Box(spacing=12)
        self.level = ui.label("…", "big")
        row.append(self.level)
        words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
        self.state = ui.label("Reading the headset", wrap=True)
        self.detail = ui.label("", "dim", wrap=True)
        words.append(self.state)
        words.append(self.detail)
        row.append(words)
        box.append(row)
        self.bar = Gtk.LevelBar(min_value=0, max_value=100, value=0)
        for offset in (Gtk.LEVEL_BAR_OFFSET_LOW, Gtk.LEVEL_BAR_OFFSET_HIGH, Gtk.LEVEL_BAR_OFFSET_FULL):
            self.bar.remove_offset_value(offset)
        box.append(self.bar)
        self.chatmix = ui.label("", "dim")
        self.chatmix.set_visible(False)
        box.append(self.chatmix)
        self.controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, css_classes=["card"], visible=False)
        self.help = Gtk.Expander(label="Not charging?", child=ui.label(CHARGING_HELP, "dim", wrap=True))
        self.widget, _inner = ui.page(box, self.controls, self.help)

    def update(self, devices):
        """devices: headset.read(). Returns whether there is a headset to show."""
        if not devices:
            self.device = None
            return False
        self.device = d = devices[0]
        self.name.set_text(d["name"])
        product = d["product"] or d["name"]
        trend = headset.charging(headset.record(product, d["battery"]), d["charging"])
        if d["battery"] is None:
            self.level.set_text("–")
            self.bar.set_value(0)
            if d["status"] == "error":
                self.state.set_text("The dongle did not answer")
                self.detail.set_text("Try unplugging the dongle and plugging it back in.")
            else:
                self.state.set_text("Headset is off or out of range")
                self.detail.set_text("The battery can only be read while it is on. It still charges while off.")
        else:
            self.level.set_text(f"{d['battery']}%")
            self.bar.set_value(d["battery"])
            low = d["battery"] <= 15 and trend != "charging"
            (self.bar.add_css_class if low else self.bar.remove_css_class)("low")
            self.state.set_text(headset.CHARGING_TEXT[trend])
            for cls in ("attention", "good"):
                self.state.remove_css_class(cls)
            if trend == "charging":
                self.state.add_css_class("good")
            elif low:
                self.state.add_css_class("attention")
            guess = "" if d["charging"] is not None or trend != "unknown" else \
                "This headset does not say when it is charging, so it is worked out from the level rising."
            left = headset.time_left_text(d["minutes_left"]) if trend != "charging" else ""
            self.detail.set_text(" · ".join(t for t in (left, guess) if t))
        self.chatmix.set_visible(d["chatmix"] is not None)
        if d["chatmix"] is not None:
            self.chatmix.set_text(f"ChatMix dial: {headset.chatmix_text(d['chatmix'])}")
        self.help.set_visible(trend != "charging")
        self._build_controls(d)
        return True


    # ---- settings -----------------------------------------------------------------------------------------------------
    def _build_controls(self, d):
        wanted = [c for c in d["capabilities"] if c in headset.FLAGS]
        key = (d["product"], tuple(wanted))
        if key == self.controls_for:
            return
        self.controls_for = key
        while child := self.controls.get_first_child():
            self.controls.remove(child)
        self.controls.set_visible(bool(wanted))
        if wanted:
            self.controls.append(Gtk.Label(label="Settings", xalign=0, css_classes=["title"]))
            self.controls.append(Gtk.Label(label="The headset cannot report these, so they show what you last set here.",
                                           xalign=0, wrap=True, css_classes=["dim"]))
        product = d["product"] or d["name"]
        for cap in wanted:
            title, help_text = headset.CONTROLS.get(cap, (cap.capitalize(), ""))
            value = headset.setting(self.ctl.memory, product, cap)
            row = Gtk.Box(spacing=10, tooltip_text=help_text)
            row.append(Gtk.Label(label=title, xalign=0, width_chars=14))
            if cap in headset.RANGES:
                low, high, step = headset.RANGES[cap]
                scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, low, high, step)
                scale.set_hexpand(True)
                scale.set_value(value)
                scale.set_draw_value(True)
                scale.set_value_pos(Gtk.PositionType.RIGHT)
                if cap == "inactive time":
                    scale.set_format_value_func(lambda _s, v: "Never" if v < 1 else f"{v:.0f} min")
                elif cap == "equalizer preset":
                    scale.set_format_value_func(lambda _s, v: f"Preset {v:.0f}")
                scale.connect("value-changed", lambda s, c=cap: self._later(c, round(s.get_value())))
                row.append(scale)
            else:
                switch = Gtk.Switch(active=bool(value), valign=Gtk.Align.CENTER, hexpand=True, halign=Gtk.Align.END)
                switch.connect("notify::active", lambda s, _p, c=cap: self._later(c, int(s.get_active()), 0))
                row.append(switch)
            self.controls.append(row)

    def _later(self, cap, value, delay=SEND_AFTER_MS):
        """Sliders send once they stop moving, so dragging does not queue dozens of commands."""
        if self.timers.get(cap):
            GLib.source_remove(self.timers[cap])
        self.timers[cap] = GLib.timeout_add(max(delay, 1), lambda: self._send(cap, value))

    def _send(self, cap, value):
        self.timers[cap] = 0
        d = self.device
        if not d:
            return False
        product = d["product"] or d["name"]

        def done(result):
            worked, said = result
            title = headset.CONTROLS.get(cap, (cap,))[0]
            if worked:
                headset.remember_setting(self.ctl.memory, product, cap, value)
                self.ctl.save()
                self.ctl.say(f"{title} set.")
            else:
                self.ctl.say(f"Could not set {title.lower()}: {said or 'the headset did not answer'}. "
                                     "Is it switched on?")
            return False
        ui.background(lambda: headset.set_control(cap, value), done)
        return False
