"""The animated launcher styles: results placed by hand on a stage and moved every frame, instead of flowing in a list
or a grid.

  orbit      a ring of apps around the search box; the one you pick turns to the top
  carousel   cards in a row, the picked one facing you and the rest turned away in 3D
  bubbles    apps float as bubbles, the ones you open most bigger and nearer the middle

The layout maths has no GTK in it (see place_orbit and friends), so it can be tested on its own."""

from __future__ import annotations

import math

ORBIT_SLOTS = 14  # how many apps fit round the ring
CAROUSEL_REACH = 4  # cards shown either side of the picked one
POP_TIME = 0.32  # seconds a bubble takes to burst
DROPLETS = 10
GOLDEN = math.pi * (3 - math.sqrt(5))  # about 137.5 degrees: sunflower seeds never line up, so bubbles do not either


def place_orbit(d: float, w: float, h: float) -> tuple | None:
    """Where an app d places from the picked one sits on the ring: (x, y, scale, opacity), or None when it is off it."""
    half = ORBIT_SLOTS / 2
    if abs(d) > half:
        return None
    radius = min(w, h) * 0.36
    angle = -math.pi / 2 + d * 2 * math.pi / ORBIT_SLOTS  # 0 is at the top
    near = max(0.0, 1 - abs(d))
    return (w / 2 + radius * math.cos(angle), h / 2 + radius * math.sin(angle), 1 + 0.55 * near,
            max(0.0, 1 - (abs(d) / half) ** 2 * 0.85))


def place_carousel(d: float, w: float, h: float) -> tuple | None:
    """(x, y, scale, opacity, turn in degrees) for a card d places from the picked one, or None past the ends."""
    ad = abs(d)
    if ad > CAROUSEL_REACH + 0.5:
        return None
    side = 1 if d > 0 else -1
    x = w / 2 + side * (min(ad, 1) * w * 0.17 + max(ad - 1, 0) * w * 0.085)
    turn = -max(-1.0, min(1.0, d)) * 58
    return x, h * 0.46, 1 - 0.25 * min(ad, 1), max(0.0, min(1.0, CAROUSEL_REACH + 0.5 - ad)), turn


def place_bubble(k: int, n: int, w: float, h: float) -> tuple[float, float]:
    """Resting place of the k-th of n bubbles: a sunflower spiral, first ones in the middle."""
    reach = math.sqrt((k + 0.5) / max(n, 1))
    return w / 2 + w * 0.43 * reach * math.cos(k * GOLDEN), h / 2 + h * 0.39 * reach * math.sin(k * GOLDEN)


def nearest(points: list, i: int, direction: str) -> int:
    """The point an arrow key leads to from point i: the closest one roughly that way. Stays put when there is none."""
    if not points or not 0 <= i < len(points):
        return i
    dx, dy = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}[direction]
    x0, y0 = points[i]
    best, best_score = i, math.inf
    for k, (x, y) in enumerate(points):
        vx, vy = x - x0, y - y0
        dist = math.hypot(vx, vy)
        if k == i or dist == 0:
            continue
        cos = (vx * dx + vy * dy) / dist
        if cos < 0.35:  # more than about 70 degrees off: not that way
            continue
        score = dist * (2.2 - cos)
        if score < best_score:
            best, best_score = k, score
    return best


def burst(e: float, radius: float) -> tuple[float, float]:
    """How far the droplets have flown and how much of them is left, e from 0 (popped) to 1 (gone)."""
    e = max(0.0, min(1.0, e))
    return radius * (1 - (1 - e) ** 3), 1 - e


def ease_out_back(x: float) -> float:
    """0 to 1 with a little overshoot, for bubbles popping in."""
    x = max(0.0, min(1.0, x)) - 1
    return 1 + 2.70158 * x ** 3 + 1.70158 * x ** 2


class Stage:
    def __init__(self, Gtk, Gsk, Graphene, kind: str):
        self.Gtk, self.Gsk, self.Graphene, self.kind = Gtk, Gsk, Graphene, kind
        self.fixed = Gtk.Fixed()
        # EXTERNAL: the stage is as big as the space it is given, whatever its children's transforms add up to
        self.widget = Gtk.ScrolledWindow(child=self.fixed, hexpand=True, vexpand=True,
                                         hscrollbar_policy=Gtk.PolicyType.EXTERNAL, vscrollbar_policy=Gtk.PolicyType.EXTERNAL)
        self.items, self.sizes, self.grow = [], {}, []
        self.pos, self.target = 0.0, 0
        self.now, self.last, self.born = 0.0, None, None
        self.drawn = None
        self.flat = None  # True when the renderer cannot turn things in 3D (the cairo one draws them pink)
        self.ring = None
        if kind == "orbit":
            self.ring = Gtk.Box(css_classes=["ring"], can_target=False)
            self.fixed.put(self.ring, 0, 0)
        self.popping = None  # a bubble bursting: its index, when it started, and what to do once it has gone
        self.bits = []  # the burst: a ring and droplets flying off
        self.caption = Gtk.Label(css_classes=["caption"], can_target=False, visible=kind == "bubbles")
        self.fixed.put(self.caption, 0, 0)
        settings = Gtk.Settings.get_default()
        self.animate = bool(settings.get_property("gtk-enable-animations")) if settings else True
        self.fixed.add_tick_callback(self._tick)

    # ---- what the launcher calls ----
    def set_items(self, widgets: list) -> None:
        for w in self.items:
            self.fixed.remove(w)
        self.items, self.sizes = list(widgets), {}
        self.grow = [1.0] * len(self.items)
        for w in self.items:
            self.fixed.put(w, 0, 0)
            w.set_opacity(0)  # placed on the next frame
        self.pos, self.target, self.born, self.drawn = 0.0, 0, None, None
        self._raise()

    def focus(self, i: int, caption: str = "") -> None:
        self.target = i
        if not self.animate:
            self.pos = i
        self.caption.set_label(caption)
        self._raise()

    def pop(self, i: int, done) -> None:
        """Burst bubble i, then call done. Straight away when animations are off."""
        if not self.animate or not 0 <= i < len(self.items) or self.popping:
            done()
            return
        self.bits = [self.Gtk.Box(css_classes=["burst"], can_target=False)]
        self.bits += [self.Gtk.Box(css_classes=["droplet"], can_target=False) for _ in range(DROPLETS)]
        for bit in self.bits:
            self.fixed.put(bit, 0, 0)
            bit.set_opacity(0)
        size = self._measure(self.items[i])[0]
        self.bits[0].set_size_request(size, size)
        self.popping = {"index": i, "start": None, "done": done}

    def step(self, i: int, direction: str) -> int:
        w, h = self._size()
        return nearest([place_bubble(k, len(self.items), w, h) for k in range(len(self.items))], i, direction)

    # ---- drawing ----
    def _size(self):
        return max(self.widget.get_width(), 1), max(self.widget.get_height(), 1)

    def _raise(self):
        """Nearer cards are drawn last, so they sit on top; the caption goes over everything."""
        if self.kind == "bubbles":
            order = [self.target] if 0 <= self.target < len(self.items) else []
        else:
            near = [k for k in range(len(self.items)) if abs(k - self.target) <= ORBIT_SLOTS]
            order = sorted(near, key=lambda k: -abs(k - self.target))
        for k in order:
            self.items[k].insert_before(self.fixed, None)
        self.caption.insert_before(self.fixed, None)

    def _measure(self, w):
        if w not in self.sizes:
            self.sizes[w] = (w.measure(self.Gtk.Orientation.HORIZONTAL, -1)[1], w.measure(self.Gtk.Orientation.VERTICAL, -1)[1])
        return self.sizes[w]

    def _put(self, w, x, y, scale=1.0, opacity=1.0, turn=0.0):
        ww, hh = self._measure(w)
        point = self.Graphene.Point
        t = self.Gsk.Transform.new().translate(point().init(x, y))
        squash = 1.0
        if turn and self.flat:
            squash = max(math.cos(math.radians(turn)), 0.35)  # a flat stand-in for the turn: narrower, as if seen edge on
        elif turn:
            t = t.perspective(900).rotate_3d(turn, self.Graphene.Vec3.y_axis())
        t = t.scale(scale * squash, scale).translate(point().init(-ww / 2, -hh / 2))
        self.fixed.set_child_transform(w, t)
        w.set_opacity(opacity)
        w.set_can_target(opacity > 0.2)

    def _tick(self, _widget, clock):
        now = clock.get_frame_time() / 1e6
        dt = 0.0 if self.last is None else min(now - self.last, 0.1)
        self.last, self.now = now, now
        if self.born is None:
            self.born = now
        if self.flat is None:
            native = self.fixed.get_native()
            renderer = native.get_renderer() if native else None
            self.flat = renderer is None or "Cairo" in type(renderer).__name__
        if self.animate:
            self.pos += (self.target - self.pos) * (1 - math.exp(-dt * 11))
        if abs(self.target - self.pos) < 0.002 or not self.animate:
            self.pos = float(self.target)
        w, h = self._size()
        moving = self.kind == "bubbles" and self.animate  # bubbles never stop drifting
        if not moving and self.drawn == (self.pos, w, h):
            return True
        self.drawn = (self.pos, w, h)
        getattr(self, f"_draw_{self.kind}")(w, h, now, dt)
        return True

    def _draw_orbit(self, w, h, _now, _dt):
        radius = min(w, h) * 0.36
        self.ring.set_size_request(round(radius * 2), round(radius * 2))
        self.fixed.set_child_transform(self.ring, self.Gsk.Transform.new().translate(
            self.Graphene.Point().init(w / 2 - radius, h / 2 - radius)))
        for k, item in enumerate(self.items):
            spot = place_orbit(k - self.pos, w, h)
            item.set_child_visible(spot is not None)
            if spot:
                self._put(item, spot[0], spot[1], spot[2], spot[3])

    def _draw_carousel(self, w, h, _now, _dt):
        for k, item in enumerate(self.items):
            spot = place_carousel(k - self.pos, w, h)
            item.set_child_visible(spot is not None)
            if spot:
                x, y, scale, opacity, turn = spot
                self._put(item, x, y, scale, opacity, turn)

    def _draw_bubbles(self, w, h, now, dt):
        n = len(self.items)
        for k, item in enumerate(self.items):
            x, y = place_bubble(k, n, w, h)
            pop = 1.0
            if self.animate:
                x += 7 * math.sin(now * 0.7 + k * 1.7)
                y += 7 * math.cos(now * 0.9 + k * 2.3)
                pop = ease_out_back((now - self.born - k * 0.008) / 0.4)
            goal = 1.32 if k == self.target else 1.0
            self.grow[k] += (goal - self.grow[k]) * ((1 - math.exp(-dt * 12)) if self.animate else 1)
            opacity = min(1.0, max(pop, 0.0) * 1.3)
            if self.popping and self.popping["index"] == k:
                if self.popping["start"] is None:
                    self.popping["start"] = now
                e = (now - self.popping["start"]) / POP_TIME
                self._draw_burst(item, x, y, e)
                # it swells, then is gone in the first third of the burst
                pop *= 1 + 0.35 * min(e * 3, 1)
                opacity = max(0.0, 1 - e * 3)
                if e >= 1:
                    done, self.popping = self.popping["done"], None
                    done()
                    return
            self._put(item, x, y, max(pop, 0.0) * self.grow[k], opacity)
            if k == self.target:
                self.sizes.pop(self.caption, None)  # its text changes, so measure it afresh each time
                ch = self._measure(self.caption)[1]
                self._put(self.caption, x, y + self._measure(item)[1] * 0.5 * self.grow[k] + ch * 0.5 + 10,
                          1.0, min(1.0, max(pop, 0.0)))
                self.caption.set_can_target(False)
                if self.popping:
                    self.caption.set_opacity(0)

    def _draw_burst(self, item, x, y, e):
        size = self._measure(item)[0] * self.grow[self.popping["index"]]
        ring, drops = self.bits[0], self.bits[1:]
        self._put(ring, x, y, 1 + 0.9 * min(e * 1.4, 1), max(0.0, 1 - e * 1.4))
        flown, left = burst(e, size * 0.95)
        for n, drop in enumerate(drops):
            angle = n * 2 * math.pi / len(drops) + 0.4
            self._put(drop, x + flown * math.cos(angle), y + flown * math.sin(angle), 0.4 + 0.6 * left, left)
