"""The window pieces of Dungeon Master mode that need no agent: dice the player throws, and the character builder."""
import math
import os
import random
import threading
import time

import cairo
from gi.repository import Adw, Gio, GLib, Gtk, Pango

import dnd_library
import dnd_mode as dm

# --- A twenty-sided die ------------------------------------------------------------------------------------------------
_PHI = (1 + 5 ** 0.5) / 2
_RAW = [(-1, _PHI, 0), (1, _PHI, 0), (-1, -_PHI, 0), (1, -_PHI, 0), (0, -1, _PHI), (0, 1, _PHI), (0, -1, -_PHI), (0, 1, -_PHI),
        (_PHI, 0, -1), (_PHI, 0, 1), (-_PHI, 0, -1), (-_PHI, 0, 1)]


def _unit(v):
    length = math.sqrt(sum(c * c for c in v)) or 1.0
    return tuple(c / length for c in v)


def _adjacent(i, j):
    return abs(sum((a - b) ** 2 for a, b in zip(_RAW[i], _RAW[j])) - 4) < 0.01


VERTICES = [_unit(v) for v in _RAW]
FACES = [(i, j, k) for i in range(12) for j in range(i + 1, 12) for k in range(j + 1, 12)
         if _adjacent(i, j) and _adjacent(j, k) and _adjacent(i, k)]
NORMALS = [_unit(tuple(sum(VERTICES[v][c] for v in f) for c in range(3))) for f in FACES]
LIGHT = _unit((-0.45, 0.65, 0.7))


def _axis_angle(axis, angle):
    x, y, z = _unit(axis)
    c, s, t = math.cos(angle), math.sin(angle), 1 - math.cos(angle)
    return ((t * x * x + c, t * x * y - s * z, t * x * z + s * y),
            (t * x * y + s * z, t * y * y + c, t * y * z - s * x),
            (t * x * z - s * y, t * y * z + s * x, t * z * z + c))


def _multiply(a, b):
    return tuple(tuple(sum(a[r][k] * b[k][c] for k in range(3)) for c in range(3)) for r in range(3))


def _apply(m, v):
    return tuple(sum(m[r][c] * v[c] for c in range(3)) for r in range(3))


def _facing_camera():
    """The resting pose: one face towards the viewer, tipped a little so the die looks solid."""
    n = NORMALS[0]
    axis = (n[1], -n[0], 0.0)
    pose = _axis_angle(axis, math.acos(max(-1.0, min(1.0, n[2])))) if any(abs(c) > 1e-6 for c in axis) else _axis_angle((0, 0, 1), 0)
    return _multiply(_axis_angle((1, 0.3, 0), -0.22), pose)


REST = _facing_camera()


class DiceArea(Gtk.DrawingArea):
    """Draws the dice: turning gently while they wait, then tumbling and bouncing to what was really rolled."""

    def __init__(self):
        super().__init__(content_width=460, content_height=210, hexpand=True)
        self.dice, self.running, self.started, self.on_land, self.landed = [], False, 0.0, None, False
        self.clock = 0.0
        self.set_draw_func(self._draw)
        self.tick = None

    def setup(self, count):
        self.dice = [{"value": None, "flash": "", "dim": False, "axis": (random.uniform(-1, 1), random.uniform(-1, 1), random.uniform(0.2, 1)),
                      "spin": random.uniform(20, 30), "delay": i * 0.1, "crit": False, "fumble": False} for i in range(count)]
        self.running, self.landed, self.on_land = False, False, None
        if self.tick is None:
            self.tick = self.add_tick_callback(self._tick)

    def throw(self, values, sides, kept, on_land):
        if len(self.dice) != len(values):
            self.setup(len(values))
        for die, value in zip(self.dice, values):
            die["value"], die["crit"], die["fumble"] = value, sides == 20 and value == 20, sides == 20 and value == 1
        if kept is not None and len(values) > 1:
            index = values.index(kept)
            for i, die in enumerate(self.dice):
                die["discard"] = i != index
        self.sides, self.running, self.started, self.on_land = sides, True, time.monotonic(), on_land

    def stop(self):
        if self.tick is not None:
            self.remove_tick_callback(self.tick)
            self.tick = None

    def _tick(self, _widget, _clock):
        self.clock += 1 / 60
        if self.running and time.monotonic() - self.started > 1.25 + 0.1 * len(self.dice):
            self.running, self.landed = False, True
            for die in self.dice:
                die["dim"] = die.get("discard", False)
            if self.on_land:
                self.on_land()
        self.queue_draw()
        return GLib.SOURCE_CONTINUE

    def _draw(self, _area, cr, w, h):
        count = max(1, len(self.dice))
        radius = min(82.0, (w / count) * 0.40, h * 0.40)
        gap = w / count
        now = time.monotonic() - self.started if self.running else None
        for i, die in enumerate(self.dice):
            x, y = gap * (i + 0.5), h * 0.54
            pose, flicker = REST, None
            if now is not None:
                p = max(0.0, min(1.0, (now - die["delay"]) / 1.25))
                left = (1 - p) ** 3
                pose = _multiply(_axis_angle(die["axis"], die["spin"] * left), REST)
                y -= abs(math.sin(p * math.pi * 3.2)) * (1 - p) ** 1.4 * h * 0.34
                if p < 0.82:
                    flicker = random.randint(1, getattr(self, "sides", 20))
            else:
                if not self.landed:
                    pose = _multiply(_axis_angle((0.3, 1, 0.2), math.sin(self.clock * 1.3 + i) * 0.35), REST)
                    y += math.sin(self.clock * 2.1 + i) * 4
            self._one(cr, x, y, radius, pose, die, flicker)

    @staticmethod
    def _one(cr, x, y, r, pose, die, flicker):
        cr.save()
        if die["dim"]:
            cr.push_group()
        if die["crit"] and die["value"] is not None and flicker is None:
            glow = cairo.RadialGradient(x, y, r * 0.3, x, y, r * 1.5)
            glow.add_color_stop_rgba(0, 1, 0.8, 0.3, 0.75)
            glow.add_color_stop_rgba(1, 1, 0.7, 0.2, 0)
            cr.set_source(glow)
            cr.arc(x, y, r * 1.5, 0, 2 * math.pi)
            cr.fill()
        base = (0.86, 0.26, 0.2) if die["fumble"] and flicker is None and die["value"] is not None else (0.86, 0.66, 0.29)
        best, best_z = None, -2.0
        for face, normal in zip(FACES, NORMALS):
            turned = _apply(pose, normal)
            if turned[2] <= 0.02:
                continue
            light = 0.32 + 0.68 * max(0.0, sum(a * b for a, b in zip(turned, LIGHT)))
            points = [_apply(pose, VERTICES[v]) for v in face]
            cr.move_to(x + points[0][0] * r, y - points[0][1] * r)
            for px, py, _pz in points[1:]:
                cr.line_to(x + px * r, y - py * r)
            cr.close_path()
            cr.set_source_rgb(*(c * light for c in base))
            cr.fill_preserve()
            cr.set_source_rgba(1, 0.93, 0.72, 0.65)
            cr.set_line_width(max(1.0, r * 0.02))
            cr.set_line_join(cairo.LINE_JOIN_ROUND)
            cr.stroke()
            if turned[2] > best_z:
                best, best_z = turned, turned[2]
        shown = flicker if flicker is not None else die["value"]
        if best is not None and shown is not None:
            text = str(shown)
            cr.select_font_face("Liberation Serif", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(r * (0.5 if len(text) < 2 else 0.42))
            extent = cr.text_extents(text)
            fx, fy = x + best[0] * r * 0.8, y - best[1] * r * 0.8
            cr.move_to(fx - extent.width / 2 - extent.x_bearing, fy - extent.height / 2 - extent.y_bearing)
            cr.set_source_rgb(0.11, 0.07, 0.03)
            cr.show_text(text)
        if die["dim"]:
            cr.pop_group_to_source()
            cr.paint_with_alpha(0.32)
        cr.restore()


class DiceTray(Gtk.Box):
    """The player's own throw: dice appear over the table, and nothing happens until they roll."""

    def __init__(self):
        super().__init__(css_classes=["dice-scrim"], visible=False, halign=Gtk.Align.FILL, valign=Gtk.Align.FILL, hexpand=True, vexpand=True)
        self.answer, self.make, self.value, self.closing = None, None, None, None
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["dice-card"], halign=Gtk.Align.CENTER,
                       valign=Gtk.Align.CENTER, hexpand=True, vexpand=True)
        self.title = Gtk.Label(css_classes=["dice-title"], wrap=True, justify=Gtk.Justification.CENTER)
        self.detail = Gtk.Label(css_classes=["dice-detail"])
        self.area = DiceArea()
        click = Gtk.GestureClick()
        click.connect("pressed", lambda *_: self._poke())
        self.area.add_controller(click)
        self.result = Gtk.Label(css_classes=["dice-result"], visible=False)
        self.button = Gtk.Button(label="Roll", css_classes=["dice-roll"], halign=Gtk.Align.CENTER)
        self.button.connect("clicked", lambda *_: self.roll())
        for widget in (self.title, self.detail, self.area, self.result, self.button):
            card.append(widget)
        self.append(card)

    def ask(self, request, make, answer):
        self.make, self.answer, self.value = make, answer, None
        self.title.set_label(request["title"])
        self.detail.set_label(request["detail"])
        self.result.set_visible(False)
        self.result.set_css_classes(["dice-result"])
        self.button.set_visible(True)
        self.area.setup(request.get("count", 1))
        self.set_visible(True)
        self.button.grab_focus()

    def _poke(self):
        if self.value is None:
            self.roll()
        elif self.area.landed:
            self._finish()

    def roll(self):
        if self.value is not None or not self.make:
            return
        self.button.set_visible(False)
        self.value = v = self.make()
        self.area.throw(v["dice"], v["sides"], v["kept"], self._landed)

    def _landed(self):
        v = self.value
        if v["kept"] is not None:
            text = f"{v['kept']} {v['bonus']:+d} = {v['total']}"
            if v["sides"] == 20 and v["kept"] == 20:
                text, css = f"Natural 20!  {text}", "crit"
            elif v["sides"] == 20 and v["kept"] == 1:
                text, css = f"Natural 1…  {text}", "fumble"
            else:
                css = ""
        else:
            extra = f" {v['bonus']:+d}" if v["bonus"] else ""
            text, css = " + ".join(str(d) for d in v["dice"]) + f"{extra} = {v['total']}", ""
        self.result.set_label(text)
        self.result.set_visible(True)
        if css:
            self.result.add_css_class(css)
        self.closing = GLib.timeout_add(1300, lambda: (self._finish(), False)[1])

    def _finish(self):
        if self.closing:
            GLib.source_remove(self.closing)
            self.closing = None
        answer, value = self.answer, self.value
        self.answer, self.make = None, None
        self.area.stop()
        self.set_visible(False)
        if answer:
            answer(value)

    def cancel(self, *_):
        """Stop was pressed: the roll is abandoned."""
        if self.closing:
            GLib.source_remove(self.closing)
            self.closing = None
        answer, self.answer, self.make, self.value = self.answer, None, None, None
        self.area.stop()
        self.set_visible(False)
        if answer:
            answer(None)


# --- The character builder --------------------------------------------------------------------------------------------
BEST_SCORES = {"barbarian": "str con dex wis cha int", "bard": "cha dex con wis int str", "cleric": "wis con str cha dex int",
               "druid": "wis con dex int cha str", "fighter": "str con dex wis cha int", "monk": "dex wis con str int cha",
               "paladin": "str cha con wis dex int", "ranger": "dex wis con str int cha", "rogue": "dex int con cha wis str",
               "sorcerer": "cha con dex wis int str", "warlock": "cha con dex wis int str", "wizard": "int con dex wis cha str"}
STEP_TITLES = {"who": "Who are you?", "class": "Choose your class", "species": "Choose your species", "background": "Choose your background",
               "abilities": "Your abilities", "skills": "Your skills", "magic": "Your magic", "ready": "Ready"}


class CharacterBuilder(Adw.Dialog):
    """Level 1, by the rules, step by step. The rules live in dnd_mode.build_character; this only offers what they allow."""

    def __init__(self, on_done):
        super().__init__(title="Forge your hero", content_width=720, content_height=760)
        self.on_done = on_done
        self.ch = {"name": "", "description": "", "class": None, "species": None, "background": None, "method": "array",
                   "pool": list(dm.STANDARD_ARRAY), "slots": {a: i for i, a in enumerate(dm.ABILITIES)}, "scores": {}, "bonus": {},
                   "bonus_style": "21", "skills": [], "spells": []}
        self._sync_scores()
        self.step = 0
        self.scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.back = Gtk.Button(label="Back", css_classes=["later"])
        self.back.connect("clicked", lambda *_: self._go(-1))
        self.where = Gtk.Label(hexpand=True, css_classes=["build-where"])
        self.next = Gtk.Button(label="Next", css_classes=["allow"])
        self.next.connect("clicked", lambda *_: self._go(1))
        bar = Gtk.Box(spacing=10, css_classes=["build-bar"])
        for widget in (self.back, self.where, self.next):
            bar.append(widget)
        self.error = Gtk.Label(css_classes=["build-error"], visible=False, wrap=True)
        view = Adw.ToolbarView(content=self.scroller, css_classes=["build"])
        view.add_top_bar(Adw.HeaderBar())
        foot = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        foot.append(self.error)
        foot.append(bar)
        view.add_bottom_bar(foot)
        self.set_child(view)
        self._show()

    # Navigation
    def steps(self):
        names = ["who", "class", "species", "background", "abilities", "skills"]
        if self.ch["class"] in dm.SPELL_CHOICES:
            names.append("magic")
        return names + ["ready"]

    def _go(self, direction):
        steps = self.steps()
        if direction > 0 and steps[self.step] == "ready":
            self._finish()
            return
        self.step = max(0, min(len(steps) - 1, self.step + direction))
        self._show()

    def _show(self):
        steps = self.steps()
        self.step = min(self.step, len(steps) - 1)
        name = steps[self.step]
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=["build-page"])
        box.append(Gtk.Label(label=STEP_TITLES[name], xalign=0, css_classes=["build-title"]))
        getattr(self, f"_page_{name}")(box)
        self.scroller.set_child(box)
        self.back.set_sensitive(self.step > 0)
        self.where.set_label(f"Step {self.step + 1} of {len(steps)}")
        self.next.set_label("Begin the adventure" if name == "ready" else "Next")
        self.error.set_visible(False)
        self._validate()

    def _validate(self):
        name = self.steps()[self.step]
        ch = self.ch
        ok = {"who": bool(ch["name"].strip()), "class": bool(ch["class"]), "species": bool(ch["species"]), "background": bool(ch["background"]),
              "abilities": self._abilities_ok(), "skills": ch["class"] is not None and len(ch["skills"]) == dm.CLASS_INFO[ch["class"]][0],
              "magic": self._magic_ok(), "ready": True}[name]
        self.next.set_sensitive(ok)

    def _finish(self):
        ok, message = dm.create_from_builder(self._final())
        if not ok:
            self.error.set_label(message)
            self.error.set_visible(True)
            return
        self.close()
        self.on_done()

    def _final(self):
        self._sync_scores()
        return {k: self.ch[k] for k in ("name", "description", "class", "species", "background", "method", "scores", "bonus", "skills", "spells")}

    # Shared bits
    def _tip_for(self, features):
        return "\n".join(f"{f}: {dm.FEATURE_TIPS[dm.feature_key(f)]}" for f in features if dm.feature_key(f) in dm.FEATURE_TIPS)

    def _cards(self, options, current, picked, tips=None):
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, min_children_per_line=2, max_children_per_line=3, column_spacing=8, row_spacing=8,
                           homogeneous=True)
        first = None
        for value, title, detail in options:
            button = Gtk.ToggleButton(css_classes=["build-card"], active=value == current, tooltip_text=(tips or {}).get(value))
            if first is None:
                first = button
            else:
                button.set_group(first)
            words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            words.append(Gtk.Label(label=title, xalign=0, css_classes=["name"]))
            if detail:
                words.append(Gtk.Label(label=detail, xalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, css_classes=["detail"], max_width_chars=26))
            button.set_child(words)
            button.connect("toggled", lambda b, v=value: b.get_active() and picked(v))
            flow.append(button)
        return flow

    @staticmethod
    def _note(text):
        return Gtk.Label(label=text, xalign=0, wrap=True, css_classes=["build-note"])

    def _choose(self, key, value):
        self.ch[key] = value
        self._validate()

    # Pages
    def _page_who(self, box):
        box.append(self._note("A name is all you need. A line about how they look helps the Dungeon Master paint them in."))
        name = Gtk.Entry(placeholder_text="Name", text=self.ch["name"], activates_default=False)
        name.connect("changed", lambda e: self._choose("name", e.get_text()))
        look = Gtk.Entry(placeholder_text="How they look (optional)", text=self.ch["description"])
        look.connect("changed", lambda e: self._choose("description", e.get_text()))
        box.append(name)
        box.append(look)
        GLib.idle_add(lambda: (name.grab_focus(), False)[1])

    def _page_class(self, box):
        def picked(value):
            if value != self.ch["class"]:
                self.ch["class"], self.ch["skills"], self.ch["spells"] = value, [], []
                if self.ch["method"] == "array":
                    order = BEST_SCORES[value].split()
                    self.ch["pool"] = list(dm.STANDARD_ARRAY)
                    self.ch["slots"] = {a: i for i, a in enumerate(order)}
                    self._sync_scores()
                self._default_bonus()
            self._validate()
        options = [(c, c.capitalize(), f"d{dm.CLASSES[c][0]} · {dm.CLASS_INFO[c][3]}") for c in dm.CLASSES]
        box.append(self._cards(options, self.ch["class"], picked, {c: self._tip_for(dm.CLASS_INFO[c][2]) for c in dm.CLASSES}))

    def _page_species(self, box):
        options = [(s, s, ", ".join(v[1][:3])) for s, v in dm.SPECIES.items()]
        box.append(self._cards(options, self.ch["species"], lambda v: self._choose("species", v), {s: self._tip_for(v[1]) for s, v in dm.SPECIES.items()}))

    def _page_background(self, box):
        box.append(self._note("Your background raises three abilities, and gives you an Origin feat, two skills and a tool. You start with 50 gp from it."))

        def picked(value):
            if value != self.ch["background"]:
                self.ch["background"], self.ch["skills"] = value, []
                self._default_bonus()
            self._validate()
        options = [(b, b, f"{' '.join(a.upper() for a in v[0])} · {v[1]} · {', '.join(s.title() for s in v[2])}") for b, v in dm.BACKGROUNDS.items()]
        box.append(self._cards(options, self.ch["background"], picked, {b: self._tip_for([v[1]]) for b, v in dm.BACKGROUNDS.items()}))

    def _default_bonus(self):
        if not self.ch["background"]:
            return
        listed = dm.BACKGROUNDS[self.ch["background"]][0]
        ranked = sorted(listed, key=lambda a: -self.ch["scores"][a])
        self.ch["bonus"] = {ranked[0]: 2, ranked[1]: 1} if self.ch["bonus_style"] == "21" else {a: 1 for a in listed}

    def _sync_scores(self):
        ch = self.ch
        if ch["method"] != "buy":
            ch["scores"] = {a: ch["pool"][ch["slots"][a]] for a in dm.ABILITIES}

    def _abilities_ok(self):
        ch = self.ch
        return ch["method"] != "buy" or sum(dm.POINT_COST[v] for v in ch["scores"].values()) <= dm.POINTS

    def _set_method(self, method):
        ch = self.ch
        if method == ch["method"]:
            return
        ch["method"] = method
        if method == "array":
            ch["pool"] = list(dm.STANDARD_ARRAY)
            ch["slots"] = {a: i for i, a in enumerate(BEST_SCORES[ch["class"]].split())}
        elif method == "roll":
            ch["pool"] = sorted(dm.roll_scores(), reverse=True)
            ch["slots"] = {a: i for i, a in enumerate(BEST_SCORES[ch["class"]].split())}
        else:
            ch["scores"] = {a: 8 for a in dm.ABILITIES}
        self._sync_scores()
        self._default_bonus()
        GLib.idle_add(lambda: (self._show(), False)[1])

    def _page_abilities(self, box):
        ch = self.ch
        box.append(self._cards([("array", "Standard array", "15, 14, 13, 12, 10, 8"), ("buy", "Point buy", f"{dm.POINTS} points, scores 8 to 15"), ("roll", "Roll them", "4d6, drop the lowest")],
                               ch["method"], self._set_method))
        if ch["method"] == "roll":
            again = Gtk.Button(label="Roll again", css_classes=["later"], halign=Gtk.Align.START)

            def reroll(*_):
                ch["pool"] = sorted(dm.roll_scores(), reverse=True)
                self._sync_scores()
                self._default_bonus()
                self._show()
            again.connect("clicked", reroll)
            box.append(again)
        if ch["method"] == "buy":
            spent = sum(dm.POINT_COST[v] for v in ch["scores"].values())
            box.append(Gtk.Label(label=f"{dm.POINTS - spent} points left", xalign=0, css_classes=["build-note"] + (["build-over"] if spent > dm.POINTS else [])))
        grid = Gtk.Grid(column_spacing=14, row_spacing=6)
        for i, a in enumerate(dm.ABILITIES):
            grid.attach(Gtk.Label(label=dm.ABILITY_NAMES[a].capitalize(), xalign=0, hexpand=True, tooltip_text=dm.ABILITY_TIPS[a]), 0, i, 1, 1)
            grid.attach(self._score_control(a), 1, i, 1, 1)
            extra = ch["bonus"].get(a, 0)
            final = ch["scores"][a] + extra
            grid.attach(Gtk.Label(label=f"+{extra}" if extra else "", css_classes=["build-note"], width_chars=3), 2, i, 1, 1)
            grid.attach(Gtk.Label(label=f"{final}  ({dm.modifier(final):+d})", css_classes=["build-final"], width_chars=9), 3, i, 1, 1)
        box.append(grid)
        self._bonus_controls(box)

    def _score_control(self, ability):
        ch = self.ch
        if ch["method"] == "buy":
            spin = Gtk.SpinButton.new_with_range(8, 15, 1)
            spin.set_value(ch["scores"][ability])

            def changed(s):
                ch["scores"][ability] = int(s.get_value())
                GLib.idle_add(lambda: (self._show(), False)[1])
            spin.connect("value-changed", changed)
            return spin
        drop = Gtk.DropDown(model=Gtk.StringList.new([str(v) for v in ch["pool"]]))
        drop.set_selected(ch["slots"][ability])

        def chosen(d, _p):
            new, old = d.get_selected(), ch["slots"][ability]
            if new == old:
                return
            other = next(a for a, i in ch["slots"].items() if i == new)
            ch["slots"][ability], ch["slots"][other] = new, old
            self._sync_scores()
            self._default_bonus()
            GLib.idle_add(lambda: (self._show(), False)[1])
        drop.connect("notify::selected", chosen)
        return drop

    def _bonus_controls(self, box):
        ch = self.ch
        listed = dm.BACKGROUNDS[ch["background"]][0]
        box.append(Gtk.Label(label=f"{ch['background']} bonus", xalign=0, css_classes=["build-section"]))

        def style(value):
            if value != ch["bonus_style"]:
                ch["bonus_style"] = value
                self._default_bonus()
                GLib.idle_add(lambda: (self._show(), False)[1])
        box.append(self._cards([("21", "+2 and +1", "Focus"), ("111", "+1, +1, +1", "Spread")], ch["bonus_style"], style))
        if ch["bonus_style"] != "21":
            return
        row = Gtk.Box(spacing=10)

        def pick(amount):
            names = [a.upper() for a in listed]
            current = next(a for a, v in ch["bonus"].items() if v == amount)
            drop = Gtk.DropDown(model=Gtk.StringList.new(names))
            drop.set_selected(listed.index(current))

            def chosen(d, _p):
                new = listed[d.get_selected()]
                if new == current:
                    return
                other = 3 - amount
                holder = next(a for a, v in ch["bonus"].items() if v == other)
                ch["bonus"] = {new: amount, (current if holder == new else holder): other}
                GLib.idle_add(lambda: (self._show(), False)[1])
            drop.connect("notify::selected", chosen)
            return drop
        row.append(Gtk.Label(label="+2 to"))
        row.append(pick(2))
        row.append(Gtk.Label(label="+1 to"))
        row.append(pick(1))
        box.append(row)

    def _page_skills(self, box):
        ch = self.ch
        count, allowed, _features, _blurb = dm.CLASS_INFO[ch["class"]]
        granted = dm.BACKGROUNDS[ch["background"]][2]
        ch["skills"] = [s for s in ch["skills"] if s not in granted]
        box.append(self._note(f"From your background: {', '.join(s.title() for s in granted)}."))
        left = Gtk.Label(xalign=0, css_classes=["build-section"])

        def update():
            suffix = " Your first two get Expertise." if ch["class"] == "rogue" else ""
            left.set_label(f"Choose {count} ({count - len(ch['skills'])} left).{suffix}")
            self._validate()
        box.append(left)
        box.append(self._picks([s for s in allowed if s not in granted], ch["skills"], count, str.title, update, dm.SKILL_TIPS))
        update()

    def _picks(self, options, chosen, limit, label, update, tips=None):
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, min_children_per_line=2, max_children_per_line=3, column_spacing=6, row_spacing=6, homogeneous=True)
        for value in options:
            button = Gtk.ToggleButton(label=label(value), active=value in chosen, css_classes=["build-pick"], tooltip_text=(tips or {}).get(value))

            def toggled(b, v=value):
                if b.get_active():
                    if v not in chosen:
                        if len(chosen) >= limit:
                            b.set_active(False)
                            return
                        chosen.append(v)
                elif v in chosen:
                    chosen.remove(v)
                update()
            button.connect("toggled", toggled)
            flow.append(button)
        return flow

    def _magic_ok(self):
        ch = self.ch
        if ch["class"] not in dm.SPELL_CHOICES:
            return True
        need_c, need_l, cantrips, level_1 = dm.SPELL_CHOICES[ch["class"]]
        return len([s for s in ch["spells"] if s in cantrips]) == need_c and len([s for s in ch["spells"] if s in level_1]) == need_l

    def _page_magic(self, box):
        ch = self.ch
        need_c, need_l, cantrips, level_1 = dm.SPELL_CHOICES[ch["class"]]
        picks_c = [s for s in ch["spells"] if s in cantrips]
        picks_l = [s for s in ch["spells"] if s in level_1 and s not in cantrips]

        def update():
            ch["spells"] = [*picks_c, *picks_l]
            self._validate()
        if need_c:
            box.append(Gtk.Label(label=f"Cantrips: choose {need_c}", xalign=0, css_classes=["build-section"]))
            box.append(self._picks(list(cantrips), picks_c, need_c, str, update, dm.SPELL_TIPS))
        box.append(Gtk.Label(label=f"Level 1 spells: choose {need_l}", xalign=0, css_classes=["build-section"]))
        box.append(self._picks(list(level_1), picks_l, need_l, str, update, dm.SPELL_TIPS))

    def _page_ready(self, box):
        try:
            args = dm.build_character(self._final())
        except (dm.Rejected, KeyError, TypeError, ValueError) as e:
            box.append(self._note(f"Something still needs choosing: {e}"))
            self.next.set_sensitive(False)
            return
        cls, scores = args["class"], args["abilities"]
        hp = dm.CLASSES[cls][0] + dm.modifier(scores["con"]) + args["hp_bonus"]
        box.append(Gtk.Label(label=args["name"], xalign=0, css_classes=["build-hero"]))
        box.append(self._note(f"{args['species']} {cls.capitalize()} 1 · {args['background']}"))
        tiles = Gtk.Box(spacing=8, homogeneous=True)
        for name, value in (("HP", hp), ("AC", args["ac"]), ("SPEED", args["speed"]), ("GOLD", args["gold"]["gp"])):
            tile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["sheet-tile"])
            tile.append(Gtk.Label(label=str(value), css_classes=["value"]))
            tile.append(Gtk.Label(label=name, css_classes=["name"]))
            tiles.append(tile)
        box.append(tiles)
        box.append(self._note("  ".join(f"{a.upper()} {scores[a]} ({dm.modifier(scores[a]):+d})" for a in dm.ABILITIES)))
        sections = [("Skills", ", ".join(s.title() for s in args["skills"])),
                    ("Gear", ", ".join(i["name"] + (f" ×{i['qty']}" if i.get("qty", 1) > 1 else "") if isinstance(i, dict) else i for i in args["equipment"])),
                    ("Features", ", ".join(args["features"]))]
        if args["spells"]:
            sections.insert(2, ("Spells", ", ".join(s["name"] for s in args["spells"])))
        for title, text in sections:
            box.append(Gtk.Label(label=title, xalign=0, css_classes=["build-section"]))
            box.append(self._note(text))


class SubclassDialog(Adw.Dialog):
    """The level 3 choice: the subclass in the rules, or one from a book the player owns."""

    def __init__(self, character, books, on_pick):
        super().__init__(title="Choose your path", content_width=620, content_height=560)
        self.on_pick, self.choice = on_pick, None
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=["build-page"])
        box.append(Gtk.Label(label=f"{character['name']} has found their calling", xalign=0, wrap=True, css_classes=["build-title"]))
        first = None
        for name, info in character["subclass_options"].items():
            button = Gtk.ToggleButton(css_classes=["build-card"], tooltip_text="\n".join(f"{f}: {t}" for f, t in info["first"]))
            first = first or button
            if button is not first:
                button.set_group(first)
            words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            words.append(Gtk.Label(label=name, xalign=0, css_classes=["name"]))
            words.append(Gtk.Label(label=info["blurb"] + "  Gain: " + ", ".join(f for f, _t in info["first"]), xalign=0, wrap=True, css_classes=["detail"]))
            button.set_child(words)
            button.connect("toggled", lambda b, n=name: b.get_active() and self._set(n, False))
            box.append(button)
        self.entry = None
        if books:
            box.append(Gtk.Label(label="OR FROM ONE OF YOUR BOOKS", xalign=0, css_classes=["build-section"]))
            self.entry = Gtk.Entry(placeholder_text="Subclass name, as your book has it")
            self.entry.connect("changed", lambda e: self._set(e.get_text().strip(), True))
            box.append(self.entry)
            box.append(Gtk.Label(label="The Dungeon Master looks it up in your books and adds what you gain.", xalign=0, wrap=True, css_classes=["build-note"]))
        self.confirm = Gtk.Button(label="Choose", css_classes=["allow"], halign=Gtk.Align.END, sensitive=False)
        self.confirm.connect("clicked", lambda *_: self._done())
        box.append(self.confirm)
        view = Adw.ToolbarView(content=Gtk.ScrolledWindow(child=box, hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True), css_classes=["build"])
        view.add_top_bar(Adw.HeaderBar())
        self.set_child(view)

    def _set(self, name, from_book):
        self.choice = (name, from_book) if name else None
        self.confirm.set_sensitive(bool(name))

    def _done(self):
        if self.choice:
            self.close()
            self.on_pick(*self.choice)


class BooksPage(Gtk.Box):
    """The player's own PDFs: add them here, and the Dungeon Master can look things up in them."""

    def __init__(self, window_getter, toast):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["sheet-page"])
        self.window_getter, self.toast = window_getter, toast
        note = Gtk.Label(label="Add rulebooks you own as PDFs. Their text stays on this PC, and the Dungeon Master looks things up in them with page numbers.",
                         wrap=True, xalign=0, css_classes=["sheet-note"])
        self.add_button = Gtk.Button(label="Add a book…", css_classes=["allow"], halign=Gtk.Align.START)
        self.add_button.connect("clicked", lambda *_: self.choose())
        self.status = Gtk.Label(xalign=0, wrap=True, css_classes=["sheet-note"], visible=False)
        self.shelf = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.query = Gtk.SearchEntry(placeholder_text="Look something up")
        self.query.connect("activate", lambda *_: self.look_up())
        self.results = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        for widget in (note, self.add_button, self.status, self.shelf, self.query, self.results):
            self.append(widget)
        self.refresh()

    def refresh(self):
        while child := self.shelf.get_first_child():
            self.shelf.remove(child)
        books = dnd_library.books()
        for book in books:
            row = Gtk.Box(spacing=8, css_classes=["sheet-row"])
            words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
            words.append(Gtk.Label(label=book["title"], xalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, css_classes=["sheet-entry-name"]))
            words.append(Gtk.Label(label=f"{book['pages']} pages", xalign=0, css_classes=["note"]))
            row.append(words)
            remove = Gtk.Button(icon_name="user-trash-symbolic", css_classes=["flat"], valign=Gtk.Align.CENTER, tooltip_text="Take this book out of the library. Your PDF is not touched.")
            remove.connect("clicked", lambda *_, i=book["id"]: self.remove(i))
            row.append(remove)
            self.shelf.append(row)
        self.query.set_visible(bool(books))

    def remove(self, book_id):
        dnd_library.remove_book(book_id)
        self.refresh()

    def choose(self):
        dialog = Gtk.FileDialog(title="Add your books", modal=True)
        pdfs = Gtk.FileFilter(name="PDF books")
        pdfs.add_suffix("pdf")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(pdfs)
        dialog.set_filters(filters)
        dialog.set_default_filter(pdfs)

        def chosen(dlg, result):
            try:
                files = dlg.open_multiple_finish(result)
            except GLib.Error:
                return
            paths = [f.get_path() for f in files if f.get_path()]
            if paths:
                self.add_books(paths)
        dialog.open_multiple(self.window_getter(), None, chosen)

    def add_books(self, paths):
        """Reads the PDFs in the background; a big book takes a little while."""
        self.add_button.set_sensitive(False)
        self.status.set_visible(True)

        def say(text):
            GLib.idle_add(lambda: (self.status.set_label(text), False)[1])

        def work():
            lines = []
            for path in paths:
                name = os.path.basename(path)
                try:
                    title, pages, empty = dnd_library.add_book(path, lambda t: say(f"{name}: {t}"))
                    lines.append(f"Added {title} ({pages} pages)." + (f" {empty} pages had no readable text." if empty else ""))
                except dnd_library.BookError as e:
                    lines.append(f"{name}: {e}.")
            GLib.idle_add(lambda: (finish(lines), False)[1])

        def finish(lines):
            self.status.set_label("\n".join(lines))
            self.add_button.set_sensitive(True)
            self.refresh()
        threading.Thread(target=work, daemon=True).start()

    def look_up(self):
        while child := self.results.get_first_child():
            self.results.remove(child)
        found = dnd_library.search(self.query.get_text())
        if not found:
            self.results.append(Gtk.Label(label="Nothing found.", xalign=0, css_classes=["sheet-note"]))
        for r in found:
            self.results.append(Gtk.Label(label=f"{r['book']}, p. {r['page']}", xalign=0, wrap=True, css_classes=["sheet-entry-name"]))
            self.results.append(Gtk.Label(label=r["text"], xalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, selectable=True, css_classes=["sheet-note"]))
